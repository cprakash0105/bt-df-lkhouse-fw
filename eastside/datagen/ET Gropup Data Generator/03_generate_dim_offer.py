import pandas as pd
pd.DataFrame([[1,'Unlimited 5G'],[2,'Family Bundle'],[3,'Student Pack'],[4,'50GB Booster'],[5,'Roaming']],columns=['offer_id','offer_name']).to_csv('dim_offer.csv',index=False)
