"""Inspect complete local sequences; not just the two packets at the jump."""
import argparse
import json
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def read(path):return [json.loads(r) for r in path.read_text(encoding='utf-8').splitlines()]


def main(result,session,output):
    if output.exists():raise ValueError('choose fresh output')
    output.mkdir(parents=True)
    data=read(result/'predictions.jsonl');anchor=1794918065.;names=['global','offline','hmm15','hmm25']
    colors=dict(global_='#c45345',offline='#8b7b53',hmm15='#23834c',hmm25='#487bb4');colors['global']=colors.pop('global_')
    logs={k:read(result/(k+'_projections.jsonl')) for k in names if k!='global'}
    lead={k:[r for r in rows if r['route']==27 and r['direction']==1 and r['vehicle']==8837137 and -35<=r['epoch']-anchor<=55] for k,rows in logs.items()}
    fig,axes=plt.subplots(3,1,figsize=(12,10),sharex=True)
    raw=lead['hmm15'];axes[0].plot([r['epoch']-anchor for r in raw],[r['raw_global'][0] for r in raw],'.-',label='global',color=colors['global'])
    for name,rows in lead.items():
        axes[0].plot([r['epoch']-anchor for r in rows],[r['projection'][0] if r['projection'] else np.nan for r in rows],'.-',label=name,color=colors[name])
    axes[0].set_ylabel('Lý trình xe dẫn (m)');axes[0].set_title('Xe dẫn 8837137: điểm bị offline loại được để trống, không nối giả')
    indices=[i for i,r in enumerate(data) if r['route']==27 and r['station']==23 and r['vehicle']==8837283 and -35<=r['epoch']-anchor<=55]
    for name in names:
        frame=pd.read_parquet(result/(name+'_features.parquet'))
        axes[1].plot([data[i]['epoch']-anchor for i in indices],frame.iloc[indices].lead_bus_speed_kmh,'.-',label=name,color=colors[name])
        axes[2].plot([data[i]['epoch']-anchor for i in indices],[data[i]['predictions'][name] for i in indices],'.-',label=name,color=colors[name])
    axes[1].set_ylabel('Feature tốc độ xe dẫn (km/h)');axes[1].set_title('Nếu xe dẫn bị loại, feature có thể đến từ xe khác/default')
    axes[2].set_ylabel('ETA xe sau (giây)');axes[2].set_xlabel('Giây so với 19:21:05, giờ Hà Nội');axes[2].set_title('Xe 8837283 → trạm thứ 23; chưa có nhãn đến trạm trong phiên')
    for ax in axes:ax.legend();ax.grid(alpha=.25)
    fig.tight_layout();fig.savefig(output/'local_sequence.png',dpi=170);plt.close(fig)
    geometry=json.loads((session/'geometry.json').read_text(encoding='utf-8'))
    points=np.array(next(g for g in geometry['geometry'] if g['route']=='27')['points'])
    lat0,lng0=21.005,105.822;ky=111132.;kx=111320*np.cos(np.radians(lat0))
    fig,ax=plt.subplots(figsize=(8,8));local=points[170:179]
    x=(local[:,2]-lng0)*kx;y=(local[:,1]-lat0)*ky
    ax.plot(x,y,'o-',color='#9d9d9d',label='Hình học tuyến có sẵn')
    for i in range(len(x)-1):
        ax.annotate('',xy=(x[i+1],y[i+1]),xytext=(x[i],y[i]),arrowprops=dict(arrowstyle='->',color='#666666'))
        ax.text((x[i]+x[i+1])/2,(y[i]+y[i+1])/2,str(170+i),fontsize=9)
    ax.plot([(r['lng']-lng0)*kx for r in raw],[(r['lat']-lat0)*ky for r in raw],'k.-',label='GPS raw theo thời gian')
    for name in ['global','hmm15']:
        projected=[]
        for r in raw:
            p=r['raw_global'] if name=='global' else r['projection']
            if not p:continue
            s,_,seg=p;a,b=points[seg],points[seg+1];length=np.hypot((b[2]-a[2])*kx,(b[1]-a[1])*ky)
            u=np.clip((s-a[3])/max(length,1e-9),0,1);lat=a[1]+u*(b[1]-a[1]);lng=a[2]+u*(b[2]-a[2]);projected.append(((lng-lng0)*kx,(lat-lat0)*ky))
        ax.plot(*np.array(projected).T,'.-',color=colors[name],label=name+' chiếu lên tuyến')
    ax.set(xlabel='Đông–Tây tương đối (m)',ylabel='Bắc–Nam tương đối (m)',title='Hai nhánh gần nhau, hướng tuyến ngược nhau\nKhông dùng đường chiếu làm ground truth vật lý')
    ax.axis('equal');ax.legend();ax.grid(alpha=.25);fig.tight_layout();fig.savefig(output/'branch_geometry.png',dpi=170);plt.close(fig)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for k in ['result','session','output']:p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args();main(a.result,a.session,a.output)
