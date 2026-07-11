# Data sources and quality

UK Sponsor Finder combines two public sources:

1. The UK Visas and Immigration **Register of licensed sponsors: workers** supplies organisation,
   location, route, and sponsorship-rating fields:
   <https://www.gov.uk/government/publications/register-of-licensed-sponsors-workers>
2. The Companies House API supplies candidate company numbers, statuses, and SIC codes:
   <https://developer.company-information.service.gov.uk/>

## Important limitations

- A sponsor licence does not mean that the organisation has an open job.
- The sponsor register does not include a Companies House number. Name-based enrichment is therefore
  probabilistic and must be treated as unverified unless name and location evidence are strong.
- Trading names, franchises, public bodies, overseas entities, and similarly named organisations may
  not have a unique Companies House match.
- Sponsorship and company status can change after a snapshot is generated.

The application should expose unknown or ambiguous matches rather than guess. Generated snapshots
should record their source URL, retrieval date, matching-policy version, and validation summary.

## Updating snapshots

Keep generated-data updates separate from application pull requests. Before replacing a snapshot:

1. Record the source URL and retrieval date.
2. Validate the expected CSV columns and row count.
3. Run the full test suite.
4. Review unmatched, ambiguous, inactive, and duplicate candidates.
5. Include a concise validation report in the pull request.

Source datasets and application code may be subject to different licensing or attribution terms.
Confirm those terms before redistributing a generated snapshot.
