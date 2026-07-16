#!/bin/bash
# Run catalog tagger post-pipeline
set -e
cd "$(dirname "$0")/../engine"

spark-submit \
  --master local[*] \
  --packages org.apache.iceberg:iceberg-spark-runtime-3.5_2.12:1.5.2 \
  catalog_tag.py \
  --config gs://eastside-lakehouse/config/pipeline.yaml \
  "${@}"
