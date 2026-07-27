import pandas as pd, random
rows=[]
for i in range(1,100001):
 rows.append([i,random.randint(1,4),random.randint(100,10000),random.randint(10,2000)])
pd.DataFrame(rows,columns=['record_id','campaign_id','impressions','conversions']).to_csv('fact_campaign_performance.csv',index=False)
