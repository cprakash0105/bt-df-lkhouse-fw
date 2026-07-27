import pandas as pd, random
rows=[]
for i in range(1,200001):
 rows.append([i,random.randint(1,50000),random.randint(1000,1039),1])
pd.DataFrame(rows,columns=['acquisition_id','customer_id','store_id','activation_flag']).to_csv('fact_subscriber_acquisition.csv',index=False)
