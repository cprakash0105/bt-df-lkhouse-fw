from setuptools import find_packages, setup

setup(
    name="eastside_dagster",
    packages=find_packages(),
    install_requires=["dagster", "google-cloud-dataproc", "google-cloud-storage", "pyyaml"],
)
