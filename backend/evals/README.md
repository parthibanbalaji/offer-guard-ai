# Evaluations

Versioned datasets live in `datasets/`; experiment definitions and result summaries live in
`experiments/`. Evaluation is kept outside runtime application code so it can depend on heavier
tooling and run independently in CI or locally.

## RAGAS offer-review evals

`ragas_offer_review.py` builds clause-level RAGAS samples from the bundled synthetic offer PDFs and
the UAE employment rule base. The coverage unit is one offer checked against one rule-base
criterion, so the current `sample_offers_v1` dataset produces 104 rows: 8 offers x 13 criteria.

Each row includes:

- retrieval inputs: criterion-specific query text and retrieved offer chunks
- generation inputs: generated clause answer text, reference answer, and expected outcome label
- metadata: offer filename, criterion id/title, rule ids, rule citations, and expected evidence

Ground truth is loaded from two dataset files:

- `expected_outcomes.json`: coarse labels such as `acceptable`, `risk`, `missing`, and `unclear`.
- `ground_truth.json`: fixture-specific reference answers and required offer evidence. When a
  fixture/criterion entry exists here, the runner uses it as `reference` and `ground_truth` instead
  of the broad auto-built rule reference.

Create the JSONL dataset without calling an LLM or vector store:

```bash
cd backend
python -m evals.ragas_offer_review
```

Run against the real eval vector collection, real generator model, and real RAGAS judge:

```bash
cd backend
python -m evals.ragas_offer_review \
  --retriever-mode weaviate \
  --eval-collection OfferGuardEvalTestChunk \
  --answer-mode generate \
  --run-ragas
```

Run only selected fixtures by full filename, stem, or numeric prefix:

```bash
cd backend
python -m evals.ragas_offer_review --retriever-mode weaviate --answer-mode generate --files 01
python -m evals.ragas_offer_review --retriever-mode weaviate --answer-mode generate --files 01 --files 07
```

Real Weaviate mode uses a deterministic fixture document id. On the first run for a fixture, it
extracts the PDF, chunks it with production chunking code, embeds chunks with the configured
embedding model, and stores them in the eval collection. On later runs, if chunks for that fixture
already exist in the eval collection, the runner reuses them and skips extraction, chunking, and
embedding for that fixture.

The generated mode uses the configured report model (`OPENROUTER_API_KEY`, `REPORT_MODEL`, and
related settings). `--run-ragas` uses a real judge LLM plus the configured embedding model for RAGAS
semantic metrics. The default reference mode is intended for smoke testing the eval plumbing; it
does not measure production generation quality.

Outputs are written under `evals/experiments/ragas_offer_review_v1/`:

- `ragas_dataset.jsonl`
- `metadata.json`
- `ragas_scores.json` when `--run-ragas` is passed

## Real run: `ragas_real_01`

The first real run was executed for fixture `01` only:

```text
backend/evals/datasets/sample_offers_v1/01_mainland_software_engineer_compliant.pdf
```

Run shape:

- selected fixture: `--files 01`
- rows evaluated: 13, one row for each rule-base criterion
- retriever: real Weaviate semantic retrieval
- eval collection: `OfferGuardEvalTestChunk`
- generator model: `openai/gpt-oss-120b`
- RAGAS judge model: `openai/gpt-oss-120b`
- outputs: `evals/experiments/ragas_real_01/`

`metadata.json` records the run configuration: selected files, row count, rule base, retriever
mode, answer mode, eval collection, retrieval limit, and timestamp.

`ragas_dataset.jsonl` is the dataset that RAGAS scored. Each line is one criterion-level sample and
contains the question, generated answer, retrieved contexts, reference answer, expected outcome,
rule ids, and citation/evidence metadata.

`ragas_scores.json` is the RAGAS result. The `summary` object is not one single document score.
It is the average score for each metric across the 13 criterion rows for this document. The `rows`
array contains per-criterion scores.

Summary from `ragas_real_01`:

```json
{
  "answer_correctness": 0.5640898143809044,
  "answer_relevancy": 0.5499841993268798,
  "context_precision": 0.9166666665930555,
  "context_recall": 0.48717948717948717,
  "faithfulness": 0.5327206981053135
}
```

The fixture-specific ground-truth rerun improved the main retrieval and generation metrics compared
with the initial broad-reference run:

```text
context_precision: 0.65 -> 0.92
context_recall:    0.04 -> 0.49
faithfulness:      0.40 -> 0.53
answer_correctness: 0.29 -> 0.56
```

Metric meaning:

- `context_precision`: how much of the retrieved context is useful for answering the criterion.
- `context_recall`: how much of the reference-required evidence was present in the retrieved
  context.
- `faithfulness`: whether the generated answer is grounded in the retrieved context.
- `answer_relevancy`: whether the generated answer addresses the criterion question.
- `answer_correctness`: whether the generated answer matches the expected/reference answer.

Score reading guide:

- `>= 0.80`: strong for that metric.
- `0.60 - 0.79`: usable, but inspect before treating as stable.
- `< 0.60`: needs investigation or tuning.

For this run, `context_precision` is the strongest summary metric at `0.92`, meaning most retrieved
chunks were relevant to the clause questions. `context_recall` improved from the initial broad
reference run but is still the weakest metric at `0.49`, meaning the retrieved contexts still did
not cover all fixture-specific reference expectations for every criterion.

Lowest per-criterion signals:

- `answer_correctness`: lowest completed score on `non_compete_restrictive_covenants` at `0.26`.
- `answer_relevancy`: lowest on `governing_law_jurisdiction` at `0.40`.
- `faithfulness`: lowest on `governing_law_jurisdiction` at `0.33`.
- `context_precision`: lowest completed score on `missing_unclear_mandatory_terms` at `0.33`.
- `context_recall`: lowest on `non_compete_restrictive_covenants` at `0.00`.

Three row-level metric values are `null` because a few RAGAS judge jobs returned malformed output or
timed out. The run used `raise_exceptions=False`, so RAGAS completed and wrote the remaining
metrics. Treat the summary as useful but not yet a hard quality gate.

## Real Run Analysis

The run did use real provider activity. The first pass embedded and stored fixture `01` chunks in
Weaviate. The answer-generation step used the report LLM for each of the 13 criteria. The RAGAS
step then used the judge LLM plus embedding model to score the generated answers.

Fixture-specific ground truth is now used for
`01_mainland_software_engineer_compliant.pdf` through `ground_truth.json`. The improved summary
above is from the rerun using concise expected answers for the actual compliant offer instead of
the broad fallback rule rubric.

The strongest result is retrieval precision. Because fixture `01` is short and the eval retrieves up
to five chunks, the retriever usually returns the relevant offer text. This is why
`context_precision` is high.

The weaker result is recall and answer quality. Even with fixture-specific ground truth, several
criteria depend on compact offer wording such as "in accordance with UAE labour law." The answer may
correctly mention missing details, but RAGAS may still mark recall or correctness lower when the
retrieved offer text does not explicitly contain every detail described in the expected answer.

The low faithfulness rows point to another issue: generated answers sometimes include legal-rule
details that are true from the rule base but not present in the retrieved offer chunks. RAGAS judges
faithfulness against retrieved contexts, so answers that mix offer evidence with statutory rule
knowledge can score poorly unless the rule text is included as context or the answer is constrained
to cite only offer facts.

The lowest recall row is `non_compete_restrictive_covenants`. That is a no-clause case: the correct
business conclusion is that no non-compete issue was identified. RAGAS context recall is awkward for
absence-of-evidence checks because there is no positive clause to retrieve. We should handle these
with a custom deterministic "absence accepted" metric instead of relying only on RAGAS recall.

The judge also produced three null metric values due malformed output/timeouts. That is a judge
reliability issue, not necessarily an app-quality issue. For production gating, we should either use
a stronger judge model, increase judge timeouts/output limits, or retry failed metric jobs.

## Improvements

- Add rule text to RAGAS contexts or split contexts into `offer_contexts` and `rule_contexts`, so
  faithfulness can judge both offer grounding and rule grounding.
- Continue replacing broad auto-built references with case-specific ground truth per fixture and
  criterion. Fixture `01` is now covered; the remaining fixtures should get the same treatment.
- Add a custom deterministic label metric for `acceptable`, `risk`, `missing`, and `unclear`
  outcomes. This will better reflect our product behavior than `answer_correctness` alone.
- Add a custom absence-of-clause metric for criteria such as non-compete in compliant offers, where
  the correct result is that no risky clause exists.
- Evaluate only applicable criteria for a narrow fixture, or mark non-applicable criteria explicitly
  so they do not drag down document-level averages.
- Tune retrieval queries for missing/implicit clauses. For example, gratuity and sick leave in
  fixture `01` are present only inside a benefits sentence, so retrieval should include broader
  benefits queries.
- Store separate generator and judge model names in `metadata.json` for future comparison runs.
- Prefer a stronger/different judge model than the generator model for production gating, so the
  evaluator is less correlated with the answer writer.
- Retry failed RAGAS judge jobs or fail the eval when null metric counts exceed an agreed threshold.
