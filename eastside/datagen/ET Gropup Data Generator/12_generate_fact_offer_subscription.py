import pandas as pd, random
rows=[]
for i in range(1,200001):
 rows.append([i,random.randint(1,50000),random.randint(1,5),round(random.uniform(10,500),2)])
pd.DataFrame(rows,columns=['subscription_id','customer_id','offer_id','revenue']).to_csv('fact_offer_subscription.csv',index=False)
