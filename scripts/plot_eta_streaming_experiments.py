"""Plots of recorded-packet shadow replay and controlled feature effects."""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np


def main(experiment,output):
    if output.exists():raise ValueError('choose fresh output')
    output.mkdir(parents=True)
    data=[json.loads(r) for r in (experiment/'predictions.jsonl').read_text(encoding='utf-8').splitlines()]
    case=[r for r in data if r['route']==27 and r['station']==23 and r['vehicle']==8837283]
    pair=[r for r in case if r['request_id']=='566b878c-df71-476d-a33f-a922bda9b82a'][0]
    case=[r for r in case if -30<=r['epoch']-pair['epoch']<=40]
    fig,ax=plt.subplots(figsize=(11,5))
    for name in ['original','carry30','motion10','motion10_carry30']:
        ax.plot([r['epoch']-pair['epoch'] for r in case],[r['predictions'][name] for r in case],marker='.',label=name)
    ax.set(xlabel='Giây so với gói 19:21:05',ylabel='ETA còn lại (giây)',title='Cùng xe, cùng trạm: phương án sửa tác động thế nào?\nReplay raw; xe 8837283, tuyến 27, trạm thứ 23; chưa có nhãn đến trạm')
    ax.axvline(0,color='gray',lw=.7);ax.grid(alpha=.25);ax.legend();fig.tight_layout();fig.savefig(output/'case_repair_comparison.png',dpi=180);plt.close(fig)
    effects=json.loads((experiment/'field_effects.json').read_text(encoding='utf-8'))
    selected=[r for r in effects if r['feature']!='baseline_eta_p50_sec'][:12]
    fig,ax=plt.subplots(figsize=(11,6))
    ax.barh([r['feature'] for r in selected][::-1],[r['p90_abs_effect_sec'] for r in selected][::-1],color='#537db8')
    ax.set(xlabel='P90 |ETA thay đổi| (giây)',title='Giữ từng field ở giá trị đầu tiên của cùng xe/trạm\nĐộ nhạy của model, không phải mức cải thiện hay nguyên nhân giao thông')
    ax.grid(axis='x',alpha=.25);fig.tight_layout();fig.savefig(output/'field_sensitivity.png',dpi=180);plt.close(fig)
    labelled=[r for r in data if r['label'] is not None]
    actual=np.array([r['label']['actual_eta_sec'] for r in labelled]);pred=np.array([r['observed_eta'] for r in labelled]);err=100*(actual-pred)/actual
    one=np.array([r['label']['hops']==1 for r in labelled])
    fig,ax=plt.subplots(figsize=(11,5))
    for mask,label,color in [(~one,'Nhiều trạm','#aab8c4'),(one,'Cách 1 trạm','#c34239')]:ax.scatter(actual[mask],err[mask],s=12,alpha=.5,label=label,c=color)
    ax.axvspan(.01,30,color='#f0b35a',alpha=.2,label='Thực tế còn dưới 30 giây')
    ax.set_xscale('log');ax.set_xlim(max(.01,actual.min()*.8),actual.max()*1.1);ax.set_ylim(-200,100);ax.axhline(0,color='black',lw=.8)
    outside=int(np.sum((err< -200)|(err>100)))
    ax.set(xlabel='Thực tế còn tới mốc qua trạm GPS (giây, thang log)',ylabel='(Thực tế − dự báo) / thực tế × 100%',title=f'Sai lệch phần trăm tăng mạnh khi mẫu số gần 0\nN={len(actual)} dự báo lặp; {outside} điểm ngoài trục Y được giữ trong CSV')
    ax.legend();ax.grid(alpha=.25);fig.tight_layout();fig.savefig(output/'percent_vs_remaining_time.png',dpi=180);plt.close(fig)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--experiment',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();main(a.experiment,a.output)
