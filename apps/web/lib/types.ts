export type Store = {id:string;brand_family:string;canonical_name:string;address:string;city:string;lat:number;lng:number;current_presence:string};
export type Observation = {id:string;observed_name:string;observed_address:string;lat:number;lng:number;source:string;source_category?:string|null;source_business_type?:string|null;observed_at:string;attributions:string[]};
export type Evidence = {id:string;evidence_type:string;title:string;source_ref?:string|null;evidence_date?:string|null;summary:string;supports_closure:boolean};
export type Closure = {id:string;store:Store;nearest_seven:Store|null;detected_at:string;last_seen_at:string;status:string;closure_date?:string|null;reason?:string|null;confidence:string;distance_m:number|null;within_100m:boolean;last_observation:Observation;evidence?:Evidence[]};
export type Filters = {status:string;brands:string[];distance:number;municipality:string;from:string;to:string;bbox?:number[];page:number};
