import pandas as pd
pd.DataFrame([[1,'5G Launch','SMS'],[2,'Family Campaign','Email'],[3,'Youth Blast','Social'],[4,'Holiday Promo','Digital']],columns=['campaign_id','campaign_name','channel']).to_csv('dim_campaign.csv',index=False)
