"""Reference-style signed percentage error distributions from recorded live labels."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from scipy.stats import gaussian_kde


def plot(rows,output,label,min_actual):
    eligible=[r for r in rows if r['actual_eta_sec']>=min_actual]
    if len(eligible)<3:return None
    actual=np.array([r['actual_eta_sec'] for r in eligible]);pred=np.array([r['predicted_eta_sec'] for r in eligible])
    assert np.all(actual>0)
    error=100*(actual-pred)/actual
    q=np.quantile(error,[.1,.25,.5,.75,.9]);lo,hi=-100,100
    events=len({(r['route'],r['vehicle'],r['trip'],r['station_order']) for r in eligible})
    vehicles=len({(r['route'],r['vehicle']) for r in eligible})
    stats=dict(rows=len(error),cohort_rows=len(rows),min_actual_sec=min_actual,arrival_events=events,vehicles=vehicles,
               mean_pct=float(error.mean()),std_pct=float(error.std()),median_pct=float(q[2]),
               p10_pct=float(q[0]),p90_pct=float(q[-1]),iqr_pct=float(q[3]-q[1]),
               wape_pct=float(100*abs(actual-pred).sum()/actual.sum()),
               negative_pct=float(100*np.mean(error<0)),positive_pct=float(100*np.mean(error>0)),
               axis_coverage_pct=float(100*np.mean((error>=lo)&(error<=hi))),outside_axis=int(np.sum((error<lo)|(error>hi))),
               formula='100 * (GPS-derived actual remaining - predicted remaining) / actual remaining',
               caveat='forecast-weighted descriptive distribution; forecasts on a vehicle/event are correlated; GPS crossing, not dwell')
    fig,(ax,box)=plt.subplots(1,2,figsize=(16,6.8),gridspec_kw={'width_ratios':[4.2,1.8]})
    bins=np.linspace(lo,hi,61);width=bins[1]-bins[0]
    # Normalize by ALL selected forecasts, retaining probability mass outside axis.
    ax.hist(error,bins=bins,weights=np.full(len(error),1/(len(error)*width)),color='#669cf1',edgecolor='white',alpha=.85,label='Histogram mật độ thực nghiệm')
    grid=np.linspace(lo,hi,700)
    if error.std()>1e-8:ax.plot(grid,gaussian_kde(error)(grid),color='#e32626',lw=2.5,label='Mật độ KDE (Scott)')
    ax.axvspan(q[0],q[-1],color='#59b88b',alpha=.17,label=f'Dải 80% sai số [{q[0]:.1f}; {q[-1]:.1f}]%')
    ax.axvline(0,color='#303744',ls='--',lw=2,label='Sai số 0')
    ax.axvline(q[2],color='#008cbf',ls=':',lw=2,label=f'Trung vị {q[2]:.1f}%')
    ax.axvline(error.mean(),color='#f06a13',ls='-.',lw=2,label=f'Trung bình {error.mean():.1f}%')
    ax.set_xlim(lo,hi);ax.set_ylim(bottom=0);ax.grid(alpha=.25,ls=':')
    ax.set_xlabel('Δ% = (thực tế GPS − dự báo) / thực tế GPS × 100%')
    ax.set_ylabel('Mật độ trên một điểm phần trăm');ax.legend(fontsize=9,loc='upper left')
    ax.text(.02,.025,'← Xe qua vị trí trạm sớm hơn dự báo',transform=ax.transAxes,color='#2455a4',fontsize=9)
    ax.text(.98,.025,'Xe qua muộn hơn dự báo →',transform=ax.transAxes,color='#ba2424',fontsize=9,ha='right')
    box.axis('off')
    content=(f"SỐ LIỆU — {label}\n\nN dùng / N nhóm: {len(error):,} / {len(rows):,}\n"
             f"Lượt qua trạm: {events}; xe: {vehicles}\nThực tế còn ≥ {min_actual:g} giây\n\n"
             f"Mean ± Std: {error.mean():.2f} ± {error.std():.2f}%\nTrung vị: {q[2]:.2f}%\nIQR: {q[3]-q[1]:.2f}%\n"
             f"Dải 80%: [{q[0]:.1f}; {q[-1]:.1f}]%\nWAPE: {stats['wape_pct']:.2f}%\n\n"
             f"Dấu âm: {stats['negative_pct']:.1f}%\nDấu dương: {stats['positive_pct']:.1f}%\n"
             f"Trong trục: {stats['axis_coverage_pct']:.1f}%\nNgoài trục: {stats['outside_axis']} dự báo\n\n"
             'Forecast lặp có tương quan.\nN không phải số mẫu độc lập.\nDải 80% là phân vị sai số,\nkhông phải khoảng dự báo ETA.')
    box.text(0,.98,content,va='top',fontsize=10.3,linespacing=1.45,bbox=dict(boxstyle='round,pad=.8',facecolor='#f6f8fa',edgecolor='#cbd4df'))
    fig.suptitle(f'Phân phối sai lệch phần trăm ETA live — {label}\nTuyến 02/27, chiều 1, ngày 17/11/2026; model đang phục vụ, nhãn qua trạm từ GPS',fontsize=14,fontweight='bold')
    fig.tight_layout(rect=[0,0,1,.91]);fig.savefig(output.with_suffix('.png'),dpi=180);plt.close(fig)
    output.with_suffix('.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2),encoding='utf-8')
    return stats


def main(analysis,output):
    if output.exists():raise ValueError('choose fresh output')
    source=analysis/'evaluated.jsonl';rows=[json.loads(l) for l in source.read_text(encoding='utf-8').splitlines()]
    output.mkdir(parents=True);reports={}
    for h in [None,1,2,5,10,15]:
        group=rows if h is None else [r for r in rows if r['hops']==h]
        for minimum in [0,30]:
            name=('all_hops' if h is None else f'k{h:02d}')+('_all_positive' if minimum==0 else '_actual_ge30')
            stats=plot(group,output/name,'Mọi khoảng cách' if h is None else f'Cách {h} trạm',minimum)
            reports[name]=stats if stats else dict(status='insufficient_rows',cohort_rows=len(group))
    with (output/'signed_percent_errors.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,['request_id','route','vehicle','station_order','trip','hops','actual_sec','predicted_sec','signed_percent'])
        writer.writeheader()
        for r in rows:writer.writerow(dict(request_id=r['request_id'],route=r['route'],vehicle=r['vehicle'],station_order=r['station_order'],trip=r['trip'],hops=r['hops'],actual_sec=r['actual_eta_sec'],predicted_sec=r['predicted_eta_sec'],signed_percent=100*(r['actual_eta_sec']-r['predicted_eta_sec'])/r['actual_eta_sec']))
    reports['source']=dict(path=str(source),sha256=hashlib.sha256(source.read_bytes()).hexdigest(),script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (output/'index.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(reports,ensure_ascii=False))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--analysis',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();main(a.analysis,a.output)
