"""Shared causal route projection for history processing and ETA serving. No I/O."""
import math
from typing import List, Optional, Sequence, Tuple

import numpy as np
import shapely

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
        self._rtree: Optional[shapely.STRtree] = None
        self._safe_lens = np.where(self._seg_lens > 1e-9, self._seg_lens, 1.0)
        self._valid_segs = self._seg_lens > 1e-9
        self._unit_dx = np.where(self._valid_segs, self._dx / self._safe_lens, 0.0)
        self._unit_dy = np.where(self._valid_segs, self._dy / self._safe_lens, 0.0)
        x2 = self._x1 + self._dx
        y2 = self._y1 + self._dy
        self._seg_min_x = np.minimum(self._x1, x2)
        self._seg_max_x = np.maximum(self._x1, x2)
        self._seg_min_y = np.minimum(self._y1, y2)
        self._seg_max_y = np.maximum(self._y1, y2)

    def _ensure_rtree(self) -> shapely.STRtree:
        """Khởi tạo lười chỉ mục không gian R-Tree (C/GEOS STRtree) trên bounding box các đoạn tuyến."""
        if self._rtree is None:
            boxes = shapely.box(
                self._seg_min_x,
                self._seg_min_y,
                self._seg_max_x,
                self._seg_max_y,
            )
            self._rtree = shapely.STRtree(boxes)
        return self._rtree

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

    def project_directed_point(
        self,
        lat: float,
        lon: float,
        ux: float,
        uy: float,
        min_cos_theta: float = 0.5,
        max_d_perp_m: float = 35.0,
    ) -> Optional[Tuple[float, float, int]]:
        """Chiếu điểm có hướng (ux, uy) dùng R-Tree STRtree O(log M), lọc cos_theta >= min_cos_theta TRƯỚC argmin."""
        px = lon * self.kx
        py = lat * self.ky
        pad = max_d_perp_m + 1e-4
        cand = self._ensure_rtree().query(shapely.box(px - pad, py - pad, px + pad, py + pad))
        if len(cand) == 0:
            return None
        cand.sort()
        cos_theta = self._unit_dx[cand] * ux + self._unit_dy[cand] * uy
        mask = self._valid_segs[cand] & (cos_theta >= min_cos_theta)
        cand = cand[mask]
        if len(cand) == 0:
            return None
        t = np.clip(
            ((px - self._x1[cand]) * self._dx[cand] + (py - self._y1[cand]) * self._dy[cand])
            / self._safe_lens_sq[cand],
            0.0,
            1.0,
        )
        dist_sq = (px - (self._x1[cand] + t * self._dx[cand])) ** 2 + (py - (self._y1[cand] + t * self._dy[cand])) ** 2
        best_pos = int(np.argmin(dist_sq))
        min_d = math.sqrt(float(dist_sq[best_pos]))
        if not math.isfinite(min_d) or min_d > max_d_perp_m:
            return None
        best_seg = int(cand[best_pos])
        best_s = round(float(self._cum_starts[best_seg] + float(t[best_pos]) * self._seg_lens[best_seg]), 1)
        s_bus = max(0.0, min(self._total_len, best_s))
        return s_bus, round(min_d, 1), best_seg

    def project_directed_points_batch(
        self,
        lats: Sequence[float],
        lons: Sequence[float],
        uxs: Sequence[float],
        uys: Sequence[float],
        min_cos_theta: float = 0.5,
        max_d_perp_m: float = 35.0,
    ) -> List[Tuple[int, float, float, int]]:
        """Chiếu hàng loạt các đỉnh có hướng bằng R-Tree STRtree + vector hóa NumPy, trả [(idx, s_m, d_perp_m, seg_idx)]."""
        n_pts = len(lats)
        if n_pts == 0:
            return []
        lat_arr = np.asarray(lats, dtype=np.float64)
        lon_arr = np.asarray(lons, dtype=np.float64)
        ux_arr = np.asarray(uxs, dtype=np.float64)
        uy_arr = np.asarray(uys, dtype=np.float64)

        active_mask = (ux_arr != 0.0) | (uy_arr != 0.0)
        if not np.any(active_mask):
            return []

        px = lon_arr * self.kx
        py = lat_arr * self.ky
        pad = max_d_perp_m + 1e-4
        active_indices = np.flatnonzero(active_mask)
        q_boxes = shapely.box(
            px[active_indices] - pad,
            py[active_indices] - pad,
            px[active_indices] + pad,
            py[active_indices] + pad,
        )
        q_pos, seg_idx = self._ensure_rtree().query(q_boxes)
        if len(q_pos) == 0:
            return []

        pt_idx = active_indices[q_pos]
        valid = self._valid_segs[seg_idx]
        cos_theta = self._unit_dx[seg_idx] * ux_arr[pt_idx] + self._unit_dy[seg_idx] * uy_arr[pt_idx]
        valid = valid & (cos_theta >= min_cos_theta)
        if not np.any(valid):
            return []

        pt_idx = pt_idx[valid]
        seg_idx = seg_idx[valid]

        p_x = px[pt_idx]
        p_y = py[pt_idx]
        dx = self._dx[seg_idx]
        dy = self._dy[seg_idx]
        x1 = self._x1[seg_idx]
        y1 = self._y1[seg_idx]
        t = np.clip(((p_x - x1) * dx + (p_y - y1) * dy) / self._safe_lens_sq[seg_idx], 0.0, 1.0)
        dist_sq = (p_x - (x1 + t * dx)) ** 2 + (p_y - (y1 + t * dy)) ** 2

        # Chọn best_seg cho từng pt_idx (giống np.argmin ưu tiên seg_idx nhỏ nhất khi hòa)
        order = np.lexsort((seg_idx, dist_sq, pt_idx))
        pt_s = pt_idx[order]
        seg_s = seg_idx[order]
        dist_sq_s = dist_sq[order]
        t_s = t[order]

        first = np.empty(len(pt_s), dtype=bool)
        first[0] = True
        first[1:] = pt_s[1:] != pt_s[:-1]

        out: List[Tuple[int, float, float, int]] = []
        max_d_sq = max_d_perp_m * max_d_perp_m
        for k in np.flatnonzero(first):
            d_sq = float(dist_sq_s[k])
            if not math.isfinite(d_sq) or d_sq > max_d_sq:
                continue
            min_d = math.sqrt(d_sq)
            if min_d > max_d_perp_m:
                continue
            seg = int(seg_s[k])
            best_s = round(float(self._cum_starts[seg] + float(t_s[k]) * self._seg_lens[seg]), 1)
            s_bus = max(0.0, min(self._total_len, best_s))
            out.append((int(pt_s[k]), s_bus, round(min_d, 1), seg))
        return out

    def project_points_corridor_batch(
        self,
        lats: Sequence[float],
        lons: Sequence[float],
        max_d_perp_m: float = 35.0,
    ) -> List[Optional[Tuple[float, float, int]]]:
        """Chiếu hàng loạt điểm GPS không cần hướng trong hành lang max_d_perp_m bằng R-Tree STRtree."""
        n_pts = len(lats)
        results: List[Optional[Tuple[float, float, int]]] = [None] * n_pts
        if n_pts == 0:
            return results
        lat_arr = np.asarray(lats, dtype=np.float64)
        lon_arr = np.asarray(lons, dtype=np.float64)
        px = lon_arr * self.kx
        py = lat_arr * self.ky
        pad = max_d_perp_m + 1e-4
        q_boxes = shapely.box(px - pad, py - pad, px + pad, py + pad)
        pt_idx, seg_idx = self._ensure_rtree().query(q_boxes)
        if len(pt_idx) == 0:
            return results

        p_x = px[pt_idx]
        p_y = py[pt_idx]
        dx = self._dx[seg_idx]
        dy = self._dy[seg_idx]
        x1 = self._x1[seg_idx]
        y1 = self._y1[seg_idx]
        t = np.clip(((p_x - x1) * dx + (p_y - y1) * dy) / self._safe_lens_sq[seg_idx], 0.0, 1.0)
        dist_sq = (p_x - (x1 + t * dx)) ** 2 + (p_y - (y1 + t * dy)) ** 2

        order = np.lexsort((seg_idx, dist_sq, pt_idx))
        pt_s = pt_idx[order]
        seg_s = seg_idx[order]
        dist_sq_s = dist_sq[order]
        t_s = t[order]

        first = np.empty(len(pt_s), dtype=bool)
        first[0] = True
        first[1:] = pt_s[1:] != pt_s[:-1]

        max_d_sq = max_d_perp_m * max_d_perp_m
        for k in np.flatnonzero(first):
            d_sq = float(dist_sq_s[k])
            if not math.isfinite(d_sq) or d_sq > max_d_sq:
                continue
            min_d = math.sqrt(d_sq)
            if min_d > max_d_perp_m:
                continue
            seg = int(seg_s[k])
            best_s = round(float(self._cum_starts[seg] + float(t_s[k]) * self._seg_lens[seg]), 1)
            s_bus = max(0.0, min(self._total_len, best_s))
            results[int(pt_s[k])] = (s_bus, round(min_d, 1), seg)
        return results


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
    def __init__(
        self,
        shape,
        sigma=15.,
        max_candidates=10,
        window=24,
        horizon=120.,
        allow_terminal_wrap=True,
        backward_window_sec=60.,
        backward_switch_margin=2.,
    ):
        self.shape=shape;self.sigma=sigma;self.max_candidates=max_candidates
        self.window=window;self.horizon=horizon
        self.allow_terminal_wrap=allow_terminal_wrap
        self.backward_window_sec=backward_window_sec
        self.backward_switch_margin=backward_switch_margin
        self.states=[];self.scores=np.array([]);self.paths=[]
        self.last=None;self.best_path=[];self.margin=None;self.reason='uninitialized'
        self.resets=0;self.rejected=0
        self.awaiting_direction=False;self.blocked_at=None;self.reversal=None
        if hasattr(shape,'_seg_min_x'):
            self._seg_min_x=shape._seg_min_x;self._seg_max_x=shape._seg_max_x
            self._seg_min_y=shape._seg_min_y;self._seg_max_y=shape._seg_max_y
        else:
            x2=shape._x1+shape._dx;y2=shape._y1+shape._dy
            self._seg_min_x=np.minimum(shape._x1,x2);self._seg_max_x=np.maximum(shape._x1,x2)
            self._seg_min_y=np.minimum(shape._y1,y2);self._seg_max_y=np.maximum(shape._y1,y2)

    def candidates(self,epoch,lat,lng,index):
        sh=self.shape;px=lng*sh.kx;py=lat*sh.ky
        pad=MAX_CORRIDOR_CROSS_TRACK_M+1e-4
        cand=np.flatnonzero(
            (px>=self._seg_min_x-pad)&(px<=self._seg_max_x+pad)
            &(py>=self._seg_min_y-pad)&(py<=self._seg_max_y+pad)
        )
        if len(cand)==0:return []
        u=np.clip(((px-sh._x1[cand])*sh._dx[cand]+(py-sh._y1[cand])*sh._dy[cand])/sh._safe_lens_sq[cand],0,1)
        d=np.hypot(px-sh._x1[cand]-u*sh._dx[cand],py-sh._y1[cand]-u*sh._dy[cand])
        s=sh._cum_starts[cand]+u*sh._seg_lens[cand]
        out=[]
        for pos in np.argsort(d,kind='mergesort'):
            if d[pos]>MAX_CORRIDOR_CROSS_TRACK_M:break
            # Adjacent polyline vertices at the same position are not independent hypotheses.
            if any(abs(s[pos]-p.s)<10 for p in out):continue
            out.append(Match(epoch,round(float(s[pos]),1),round(float(d[pos]),1),int(cand[pos]),index))
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
                for idx_a,a in enumerate(self.states):
                    ds=b.s-a.s
                    recent_floor_ref=a.s
                    if self.backward_window_sec>0 and self.paths[idx_a]:
                        recent_pts=[p.s for p in self.paths[idx_a] if epoch-p.epoch<=self.backward_window_sec]
                        if recent_pts:
                            recent_floor_ref=max(recent_pts)
                    terminal=(self.allow_terminal_wrap and self.shape._total_len>1000 and a.s>=self.shape._total_len-TERMINAL_RESET_ZONE_M and b.s<=TERMINAL_RESET_ZONE_M and b.s<a.s-MAX_GPS_BACKWARD_JITTER_M)
                    if terminal:
                        distance=self.shape._total_len-a.s+b.s
                        penalty=4.
                    elif ds>=-MAX_GPS_BACKWARD_JITTER_M and b.s>=recent_floor_ref-MAX_GPS_BACKWARD_JITTER_M:
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
                    wrapped=(self.allow_terminal_wrap and self.shape._total_len>1000 and a.s>=self.shape._total_len-TERMINAL_RESET_ZONE_M and b.s<=TERMINAL_RESET_ZONE_M and b.s<a.s-MAX_GPS_BACKWARD_JITTER_M)
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
        prev_s=self.best_path[-1].s if self.best_path else None
        if (
            self.backward_switch_margin>0
            and prev_s is not None
            and old is not None
            and dt<=STALE_DELTA_T_MAX_SEC
            and self.reason!='initialized'
            and len(self.paths[best])>1
            and self.states[best].s<prev_s-MAX_GPS_BACKWARD_JITTER_M
        ):
            fwd_indices=[k for k,st in enumerate(self.states) if st.s>=prev_s-MAX_GPS_BACKWARD_JITTER_M]
            if fwd_indices:
                fwd_best=max(fwd_indices,key=lambda k:self.scores[k])
                if (self.scores[best]-self.scores[fwd_best])<self.backward_switch_margin:
                    best=fwd_best
        ordered=np.sort(self.scores);self.margin=float(ordered[-1]-ordered[-2]) if len(ordered)>1 else None
        self.best_path=self.paths[best];self.last=(epoch,lat,lng)
        if old and dt<=STALE_DELTA_T_MAX_SEC and len(self.best_path)==1 and self.reason!='initialized':
            self.reason='terminal_reset';self.resets+=1
        return self.best_path[-1]
