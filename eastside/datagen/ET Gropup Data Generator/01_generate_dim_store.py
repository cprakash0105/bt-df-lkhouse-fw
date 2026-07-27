import pandas as pd, random
stores=[]
states=['Tamil Nadu','Karnataka','Maharashtra','Delhi','Telangana']
cities={'Tamil Nadu':['Chennai','Coimbatore'],'Karnataka':['Bengaluru','Mysuru'],'Maharashtra':['Mumbai','Pune'],'Delhi':['New Delhi'],'Telangana':['Hyderabad']}
sid=1000
for st in states:
    for city in cities[st]:
        for i in range(1,6):
            stores.append([sid,f'ET {city} Store {i}','Retail',city,st,'India'])
            sid+=1
pd.DataFrame(stores,columns=['store_id','store_name','store_type','city','state','country']).to_csv('dim_store.csv',index=False)
