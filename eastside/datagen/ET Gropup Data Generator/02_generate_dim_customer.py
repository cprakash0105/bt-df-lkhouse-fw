import pandas as pd, random
rows=[]
for cid in range(1,50001):
 rows.append([cid,random.choice(['M','F']),random.randint(18,70),random.choice(['Youth','Family','Enterprise','Premium'])])
pd.DataFrame(rows,columns=['customer_id','gender','age','customer_segment']).to_csv('dim_customer.csv',index=False)
