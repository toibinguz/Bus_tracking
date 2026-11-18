"""Explicit pre-HMM projection baseline for recorded-data experiments only.

Uses the current feature formulas with the former independent nearest-point
projection. Production must use OnlineFeatureExtractor, not this reference.
"""
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.online_features import OnlineFeatureExtractor


class GlobalProjectionReference(OnlineFeatureExtractor):
    def project_vehicle(self,route_id,dir_int,vehicle,now_epoch):
        shape=self._get_shape_model(route_id,'go' if dir_int==0 else 're')
        projection=shape.project_point(vehicle.lat,vehicle.lng) if shape else None
        return vehicle.model_copy(update={'projection_checked':True,'matched_projection':projection,
                                          'projection_status':'legacy_global_reference'})
