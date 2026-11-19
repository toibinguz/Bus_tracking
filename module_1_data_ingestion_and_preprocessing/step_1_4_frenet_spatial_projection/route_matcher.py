"""Shared causal route projection for history processing and ETA serving. No I/O."""
import math
from typing import List, Sequence, Tuple

import numpy as np

from config.system_config import (
    METERS_PER_DEG_LAT,
    METERS_PER_DEG_LON_EQUATOR,
)


class ShapeProjectionModel:
    """Mô hình chiếu trực giao Cartesian 1D cho 1 tim tuyến (route_id, direction)."""

    def __init__(
        self,
        kx: float,
        ky: float,
        x1: np.ndarray,
        y1: np.ndarray,
        dx: np.ndarray,
        dy: np.ndarray,
        safe_lens_sq: np.ndarray,
        seg_lens: np.ndarray,
        cum_starts: np.ndarray,
        total_len: float,
    ):
        self.kx = kx
        self.ky = ky
        self._x1 = x1
        self._y1 = y1
        self._dx = dx
        self._dy = dy
        self._safe_lens_sq = safe_lens_sq
        self._seg_lens = seg_lens
        self._cum_starts = cum_starts
        self._total_len = total_len

    @classmethod
    def build(cls, shape_points: Sequence[Tuple[float, float, float, float]]) -> "ShapeProjectionModel":
        """shape_points = [(point_order, lat, lon, cum_distance_m)] sắp xếp theo point_order tăng dần."""
        s_lats = np.array([float(p[1]) for p in shape_points], dtype=np.float64)
        s_lons = np.array([float(p[2]) for p in shape_points], dtype=np.float64)
        s_cums = np.array([float(p[3]) for p in shape_points], dtype=np.float64)

        mean_lat = float(np.mean(s_lats))
        kx = METERS_PER_DEG_LON_EQUATOR * math.cos(math.radians(mean_lat))
        ky = METERS_PER_DEG_LAT

        x1 = s_lons[:-1] * kx
        y1 = s_lats[:-1] * ky
        x2 = s_lons[1:] * kx
        y2 = s_lats[1:] * ky

        dx = x2 - x1
        dy = y2 - y1
        seg_lens_sq = dx * dx + dy * dy
        safe_lens_sq = np.maximum(seg_lens_sq, 1e-6)
        seg_lens = np.sqrt(seg_lens_sq)
        cum_starts = s_cums[:-1]

        return cls(
            kx=kx,
            ky=ky,
            x1=x1,
            y1=y1,
            dx=dx,
            dy=dy,
            safe_lens_sq=safe_lens_sq,
            seg_lens=seg_lens,
            cum_starts=cum_starts,
            total_len=float(s_cums[-1]),
        )

    def project_point(self, lat: float, lon: float) -> Tuple[float, float, int]:
        """
        Chiếu trực giao điểm GPS (lat, lon) lên toàn bộ tim tuyến (Global Search).
        Trả về (s_bus_m, d_perp_m, seg_idx) — làm tròn 1 chữ số thập phân như module 1.4.
        """
        px = lon * self.kx
        py = lat * self.ky

        p_dx1 = px - self._x1
        p_dy1 = py - self._y1
        t = np.clip((p_dx1 * self._dx + p_dy1 * self._dy) / self._safe_lens_sq, 0.0, 1.0)
        proj_x = self._x1 + t * self._dx
        proj_y = self._y1 + t * self._dy
        dist_sq = (px - proj_x) ** 2 + (py - proj_y) ** 2
        best_seg = int(np.argmin(dist_sq))

        min_d = math.sqrt(float(dist_sq[best_seg]))
        best_t = float(t[best_seg])
        best_s = round(float(self._cum_starts[best_seg] + best_t * self._seg_lens[best_seg]), 1)
        s_bus = max(0.0, min(self._total_len, best_s))
        return s_bus, round(min_d, 1), best_seg

    def segment_unit_tangent(self, seg_idx: int) -> Tuple[float, float]:
        """Vector đơn vị tiếp tuyến tim tuyến tại đoạn seg_idx theo (East, North)."""
        idx = int(min(max(0, seg_idx), len(self._dx) - 1))
        seg_len = float(self._seg_lens[idx])
        if seg_len < 1e-9:
            return 1.0, 0.0
        return float(self._dx[idx] / seg_len), float(self._dy[idx] / seg_len)


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
        self.awaiting_direction=False;self.blocked_at=None;self.reversal=None

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
        if self.awaiting_direction:
            if epoch-self.blocked_at<=STALE_DELTA_T_MAX_SEC:
                self.reason='direction_change_pending';return None
            self.awaiting_direction=False
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
                    terminal=(self.shape._total_len>1000 and a.s>=self.shape._total_len-TERMINAL_RESET_ZONE_M and b.s<=TERMINAL_RESET_ZONE_M and b.s<a.s-MAX_GPS_BACKWARD_JITTER_M)
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
                self.rejected+=1;self.reason='no_feasible_transition'
                prior=self.best_path[-1]
                near_terminal=min(prior.s,self.shape._total_len-prior.s)<=TERMINAL_RESET_ZONE_M
                nearest=min(new,key=lambda p:p.cross_track)
                if near_terminal and nearest.s<prior.s-MAX_GPS_BACKWARD_JITTER_M and move>=8:
                    previous=self.reversal
                    moved_from_previous=np.hypot((lng-previous[4])*self.shape.kx,(lat-previous[3])*self.shape.ky) if previous else 0
                    count=previous[2]+1 if previous and epoch>previous[0] and nearest.s<=previous[1]+MAX_GPS_BACKWARD_JITTER_M and moved_from_previous>=8 else (previous[2] if previous else 1)
                    if previous is None or moved_from_previous>=8:self.reversal=(epoch,nearest.s,count,lat,lng)
                    if count>=2:
                        # The current direction is no longer trustworthy. Do not
                        # serve a returning bus against the old stop sequence.
                        self.states=[];self.scores=np.array([]);self.paths=[];self.best_path=[];self.last=None
                        self.awaiting_direction=True;self.blocked_at=epoch;self.resets+=1
                        self.reason='direction_change_pending'
                else:self.reversal=None
                return None
            self.reason='matched'
            self.reversal=None
        valid=np.isfinite(scores);self.states=[p for p,ok in zip(new,valid) if ok]
        self.paths=[p for p,ok in zip(paths,valid) if ok];self.scores=scores[valid]
        self.scores-=self.scores.max();best=int(np.argmax(self.scores))
        ordered=np.sort(self.scores);self.margin=float(ordered[-1]-ordered[-2]) if len(ordered)>1 else None
        self.best_path=self.paths[best];self.last=(epoch,lat,lng)
        if old and dt<=STALE_DELTA_T_MAX_SEC and len(self.best_path)==1 and self.reason!='initialized':
            self.reason='terminal_reset';self.resets+=1
        return self.best_path[-1]
