"""PIT-only modelling API; no daily value can masquerade as an intraday quote.

Requires independently audited feature availability and target availability.
Imputation, scaling, fitting and calibration stay inside each historical fold.
Missing inputs raise DataUnavailable; they never become zero or fake forecasts.
"""
import numpy as np,pandas as pd
from sklearn.pipeline import make_pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge,LogisticRegression
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.calibration import CalibratedClassifierCV
class DataUnavailable(ValueError):pass
def validate_panel(panel,features):
 required=['decision_at','feature_available_at','target_available_at','target','vintage_verified','intraday_quote_verified']+features
 if any(c not in panel for c in required):raise DataUnavailable('Missing PIT contract fields')
 for col in ['decision_at','feature_available_at','target_available_at']:
  if panel[col].isna().any() or getattr(panel[col].dt,'tz',None) is None:raise DataUnavailable('Timestamp must be timezone aware and nonempty: '+col)
 if not panel.vintage_verified.all() or not panel.intraday_quote_verified.all():raise DataUnavailable('Unverified vintage/intraday data')
 if (panel.feature_available_at>panel.decision_at).any():raise DataUnavailable('Feature was unavailable at decision time')
 if (panel.target_available_at<=panel.decision_at).any():raise DataUnavailable('Forecast target already known')
def regression_fold(panel,features,train_end,test_start,test_end,method='ridge'):
 validate_panel(panel,features)
 train=panel[(panel.decision_at<train_end)&(panel.target_available_at<test_start)].copy()
 test=panel[(panel.decision_at>=test_start)&(panel.decision_at<test_end)].copy()
 if len(train)<252 or len(test)<30:raise DataUnavailable('Insufficient observations')
 estimator=Ridge(alpha=10.) if method=='ridge' else HistGradientBoostingRegressor(max_iter=100,max_leaf_nodes=7,l2_regularization=10,random_state=125)
 model=make_pipeline(SimpleImputer(strategy='median'),StandardScaler(),estimator)
 model.fit(train[features],train.target)
 pred=model.predict(test[features]);err=pred-test.target.to_numpy()
 return pd.DataFrame({'decision_at':test.decision_at,'target':test.target,'prediction':pred,'error':err}),model
def probabilistic_fold(panel,features,train_end,cal_start,test_start,test_end):
 validate_panel(panel,features)
 # Explicit chronological fit/calibration split; no random CV on serial data.
 train=panel[(panel.decision_at<cal_start)&(panel.target_available_at<cal_start)]
 cal=panel[(panel.decision_at>=cal_start)&(panel.decision_at<train_end)&(panel.target_available_at<test_start)]
 test=panel[(panel.decision_at>=test_start)&(panel.decision_at<test_end)]
 if min(len(train),len(cal),len(test))<100:raise DataUnavailable('Insufficient chronological calibration sample')
 model=make_pipeline(SimpleImputer(),StandardScaler(),LogisticRegression(C=.1,max_iter=1000,random_state=125))
 model.fit(train[features],train.target)
 # Fit a multinomial calibrator on out-of-fit log probabilities.
 logits=np.log(np.clip(model.predict_proba(cal[features]),1e-6,1))
 calibrator=LogisticRegression(C=1.,max_iter=1000,random_state=125).fit(logits,cal.target)
 probs=calibrator.predict_proba(np.log(np.clip(model.predict_proba(test[features]),1e-6,1)))
 return test.decision_at,probs,calibrator.classes_,model,calibrator
def availability_join(decisions,observations):
 """Each revision is its own observation with its own actual availability."""
 if observations.available_at.isna().any():raise DataUnavailable('Missing actual first-seen/publication timestamp')
 return pd.merge_asof(decisions.sort_values('decision_at'),observations.sort_values('available_at'),left_on='decision_at',right_on='available_at',direction='backward',allow_exact_matches=True,tolerance=pd.Timedelta(days=4))
