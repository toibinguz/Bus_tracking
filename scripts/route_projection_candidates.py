"""Experimental causal route HMM. Kept outside production until raw validation.

Scores are relative model scores, not calibrated probabilities. Timestamp denotes
the recorded source timestamp (fetch time for TimBus), not asserted device time.
"""
from dataclasses import dataclass
import numpy as np

from config.system_config import MAX_CORRIDOR_CROSS_TRACK_M,MAX_GPS_BACKWARD_JITTER_M,FRENET_MAX_SPEED_MPS,TERMINAL_RESET_ZONE_M,STALE_DELTA_T_MAX_SEC


@dataclass(frozen=True)
class Match:
    epoch: float
    s: float
    cross_track: float
    segment: int
    observation: int


class RouteHMM:
    def __init__(self,shape,sigma=15.,max_candidates=10,window=24,horizon=120.):
        self.shape=shape;self.sigma=sigma;self.max_candidates=max_candidates
        self.window=window;self.horizon=horizon
        self.states=[];self.scores=np.array([]);self.paths=[]
        self.last=None;self.best_path=[];self.margin=None;self.reason='uninitialized'
        self.resets=0;self.rejected=0

    def candidates(self,epoch,lat,lng,index):
        sh=self.shape;px=lng*sh.kx;py=lat*sh.ky
        u=np.clip(((px-sh._x1)*sh._dx+(py-sh._y1)*sh._dy)/sh._safe_lens_sq,0,1)
        d=np.hypot(px-sh._x1-u*sh._dx,py-sh._y1-u*sh._dy)
        s=sh._cum_starts+u*sh._seg_lens
        out=[]
        for i in np.argsort(d):
            if d[i]>MAX_CORRIDOR_CROSS_TRACK_M:break
            # Adjacent polyline vertices at the same position are not independent hypotheses.
            if any(abs(s[i]-p.s)<10 for p in out):continue
            out.append(Match(epoch,round(float(s[i]),1),round(float(d[i]),1),int(i),index))
            if len(out)>=self.max_candidates:break
        return out

    def update(self,epoch,lat,lng,index):
        if self.last and epoch<=self.last[0]:
            self.reason='late_or_duplicate';return self.best_path[-1] if self.best_path else None
        new=self.candidates(epoch,lat,lng,index)
        if not new:
            self.rejected+=1;self.reason='outside_corridor';return None
        old=self.last;dt=epoch-old[0] if old else None
        move=np.hypot((lng-old[2])*self.shape.kx,(lat-old[1])*self.shape.ky) if old else 0.
        emission=-.5*(np.array([p.cross_track for p in new])/self.sigma)**2
        # Repeated coordinates with a fresh fetch timestamp are not new independent spatial evidence.
        if old and lat==old[1] and lng==old[2]:emission[:]=0
        if old and dt<=30 and move>=self.sigma:
            mx=(lng-old[2])*self.shape.kx;my=(lat-old[1])*self.shape.ky
            for i,p in enumerate(new):
                ux,uy=self.shape.segment_unit_tangent(p.segment)
                emission[i]-=2*(1-(mx*ux+my*uy)/move)
        if not self.states or dt>STALE_DELTA_T_MAX_SEC:
            if self.states:self.resets+=1
            scores=emission;paths=[[p] for p in new];self.reason='initialized'
        else:
            scores=np.full(len(new),-np.inf);paths=[None]*len(new)
            for j,b in enumerate(new):
                transitions=[]
                for a in self.states:
                    ds=b.s-a.s
                    terminal=(self.shape._total_len>1000 and a.s>=self.shape._total_len-TERMINAL_RESET_ZONE_M and b.s<=TERMINAL_RESET_ZONE_M)
                    if terminal:
                        distance=self.shape._total_len-a.s+b.s
                        penalty=4.
                    elif ds>=-MAX_GPS_BACKWARD_JITTER_M:
                        distance=max(0,ds);penalty=max(0,-ds)/self.sigma
                    else:
                        transitions.append(-np.inf);continue
                    if distance>dt*FRENET_MAX_SPEED_MPS+3*self.sigma:
                        transitions.append(-np.inf);continue
                    transitions.append(-abs(distance-move)/self.sigma-penalty)
                options=self.scores+np.array(transitions);parent=int(np.argmax(options))
                if np.isfinite(options[parent]):
                    scores[j]=options[parent]+emission[j]
                    a=self.states[parent]
                    wrapped=(self.shape._total_len>1000 and a.s>=self.shape._total_len-TERMINAL_RESET_ZONE_M and b.s<=TERMINAL_RESET_ZONE_M and b.s<a.s-MAX_GPS_BACKWARD_JITTER_M)
                    paths[j]=[b] if wrapped else (self.paths[parent]+[b])[-self.window:]
                    while len(paths[j])>2 and epoch-paths[j][0].epoch>self.horizon:paths[j].pop(0)
            if not np.isfinite(scores).any():
                self.rejected+=1;self.reason='no_feasible_transition';return None
            self.reason='matched'
        valid=np.isfinite(scores);self.states=[p for p,ok in zip(new,valid) if ok]
        self.paths=[p for p,ok in zip(paths,valid) if ok];self.scores=scores[valid]
        self.scores-=self.scores.max();best=int(np.argmax(self.scores))
        ordered=np.sort(self.scores);self.margin=float(ordered[-1]-ordered[-2]) if len(ordered)>1 else None
        self.best_path=self.paths[best];self.last=(epoch,lat,lng)
        if old and dt<=STALE_DELTA_T_MAX_SEC and len(self.best_path)==1 and self.reason!='initialized':
            self.reason='terminal_reset';self.resets+=1
        return self.best_path[-1]
