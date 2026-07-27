import pandas as pd, random
rows=[]
for i in range(1,500001):
 rows.append([i,random.randint(1,50000),random.choice(['SMS Delivered','Email Opened','Offer Clicked','Offer Purchased'])])
pd.DataFrame(rows,columns=['event_id','customer_id','event_type']).to_csv('fact_customer_interactions.csv',index=False)
