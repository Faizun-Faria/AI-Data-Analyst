-- Fails the build when any batch's counts don't add up (user story US-04): rows counted at
-- ingestion, loaded into bronze, and split between the marts and quarantine must all match.
-- The failing rows name the batch; `python run_pipeline.py transform` prints them.

select *
from {{ ref('completeness_by_batch') }}
where not is_complete
