import subprocess,sys
scripts=['01_generate_dim_store.py','02_generate_dim_customer.py','03_generate_dim_offer.py','04_generate_dim_campaign.py','11_generate_fact_subscriber_acquisition.py','12_generate_fact_offer_subscription.py','13_generate_fact_campaign_performance.py','14_generate_fact_customer_interactions.py']
for s in scripts: subprocess.run([sys.executable,s],check=True)
print('ET Group data product datasets generated')
