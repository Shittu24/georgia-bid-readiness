select model_run_id,model_id,model_revision,prompt_version,approach,config_sha256,dataset_snapshot_id from {{ source('core','model_runs') }}
