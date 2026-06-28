# Vector database choice

## Decision

Use **Weaviate locally** for OfferGuard's retrieval layer.

The main reason is Weaviate's native hybrid search: it can combine vector
similarity with keyword/BM25-style matching in one retrieval flow. That matters
for legal and offer-letter review because important evidence is often attached
to exact terms such as probation, notice, gratuity, leave, termination,
non-compete, visa, jurisdiction, salary, and working hours.

If we decide that operational simplicity matters more than native vector-store
features, the correct alternative is **pgvector**, because PostgreSQL is already
part of the architecture and remains the system of record.

## Durable source notes

This document preserves the decision-useful substance from the Groovy Web 2026
vector database comparison:
<https://www.groovyweb.co/blog/vector-database-comparison-2026>.

The source article may change or disappear, so the notes below capture the
comparison in OfferGuard-specific terms rather than relying only on the link.

### Comparison summary

| Database | Best fit | Strengths | Tradeoffs for OfferGuard |
|---|---|---|---|
| Weaviate | Production-shaped RAG with semantic plus lexical retrieval | Native hybrid search, schema support, metadata filtering, local Docker support, scalable path | More infrastructure and configuration than a minimal prototype store |
| pgvector | Teams already committed to PostgreSQL | One primary database to operate, SQL-native filtering, transactional metadata, strong fit when Postgres is already present | Hybrid search is assembled from PostgreSQL full-text search plus vector search rather than provided as a single native vector-database feature |
| Qdrant | High-performance open-source vector search | Strong filtering, good performance profile, simple operations compared with heavier engines | Does not remove the need to design hybrid/legal-term retrieval behavior |
| Milvus | Large-scale vector workloads | Designed for very large vector datasets and high-throughput retrieval | Operationally heavier than this project needs right now |
| Pinecone | Managed vector database | Low operations burden, managed scaling | External managed service; less aligned with local-first portfolio architecture |
| Elasticsearch/OpenSearch | Search-first systems with vector support | Mature lexical search and filtering, good for search-heavy products | Heavier stack if OfferGuard only needs RAG retrieval, not a broad search platform |

### Practical interpretation

The article's useful framing is not that one vector database is universally
best. The right choice depends on the product's retrieval pattern:

- Choose **Weaviate** when hybrid semantic plus keyword search should be a core
  feature of the retrieval layer.
- Choose **pgvector** when minimizing infrastructure is more valuable than
  specialized vector-database features.
- Choose **Qdrant, Milvus, Pinecone, Elasticsearch, or OpenSearch** when the
  project has scale, search, managed-service, or operations needs that clearly
  exceed a local MVP.

## OfferGuard requirements

OfferGuard retrieval has two indexes:

- Uploaded offer-letter chunks.
- Curated UAE employment-rule chunks.

The database must support:

- Local Docker development.
- Rebuildable collections from source chunks.
- Metadata filters for document id, clause name, source type, jurisdiction,
  effective date, page number, extraction quality, and legal review date.
- Stable ids so evidence citations can point back to PostgreSQL records and
  MinIO objects.
- Top-k semantic retrieval for each fixed clause.
- Hybrid retrieval that combines semantic similarity with exact legal and
  offer-letter terms.

## Why Weaviate

Weaviate is the preferred choice because native hybrid search fits the product
better than pure vector search.

OfferGuard does not retrieve generic knowledge. It retrieves legally meaningful
evidence. Exact words and phrases matter. A clause can be semantically related
while still missing the legally important term; conversely, a chunk can contain
the exact term but need semantic ranking to decide whether it is actually useful
for the clause being reviewed.

Weaviate gives us a cleaner first-class path for:

- Semantic plus keyword retrieval in one vector-store query.
- Tunable balance between vector similarity and lexical matches.
- Metadata filters for clause, document, jurisdiction, source type, and review
  dates.
- Local Docker usage that still resembles a production vector service.
- Future tenant or collection isolation if OfferGuard grows beyond a single
  local workflow.

## Retrieval shape

OfferGuard's clause review benefits from:

```text
extract -> chunk -> embed -> hybrid search -> filter -> rerank -> cite evidence
```

That makes Weaviate the right default.

## pgvector alternative

pgvector is the right alternative if we want to keep the architecture simpler by
using PostgreSQL for both relational metadata and vector search.

Yes, pgvector can support hybrid search, but the implementation shape is
different from Weaviate:

- pgvector provides vector similarity search inside PostgreSQL.
- PostgreSQL provides full-text search for lexical matching.
- The application combines both result sets with SQL ranking, Reciprocal Rank
  Fusion, cross-encoder reranking, or a custom weighted score.

So the answer is:

```text
Can pgvector do hybrid search? Yes.
Is it native in the same way Weaviate hybrid search is native? No.
```

This is not a weakness if we want SQL control. It may even be a good fit for
OfferGuard because legal retrieval often needs deterministic filters and clear
ranking logic. The cost is that we own more ranking design ourselves.

Choose pgvector if:

- We want fewer moving services.
- PostgreSQL metadata and vector chunks should live together.
- We want SQL-native filtering, joins, and transactional updates.
- We are comfortable building and testing the hybrid ranking logic ourselves.

Choose Weaviate if:

- Native hybrid search is a product-level requirement.
- We want the vector store to own vector plus lexical retrieval behavior.
- We prefer a clearer path to vector-database production features.
- We want less custom ranking infrastructure in application code.

## Implementation recommendation

Proceed with Weaviate, but avoid coupling the Evidence Retrieval Agent directly
to Weaviate client APIs.

Application code should depend on a local interface:

```python
class VectorStore:
    async def upsert_chunks(self, collection: str, chunks: list[VectorChunk]) -> None:
        ...

    async def search(
        self,
        collection: str,
        query: str,
        filters: dict[str, object],
        top_k: int,
    ) -> list[RetrievedChunk]:
        ...
```

The first implementation can be `WeaviateVectorStore`. If we later choose
pgvector, we can add `PgVectorStore` without rewriting the agent workflow.

## Weaviate implementation checklist

1. Run a Weaviate service in `compose.yaml` with a persistent volume.
2. Configure neutral vector-store settings, for example:

   ```text
   OFFERGUARD_VECTOR_STORE=weaviate
   OFFERGUARD_VECTOR_HOST=weaviate
   OFFERGUARD_VECTOR_HTTP_PORT=8080
   OFFERGUARD_VECTOR_GRPC_PORT=50051
   ```

3. Add the Weaviate Python client.
4. Add a `VectorStore` adapter interface before writing retrieval code.
5. Create collections for offer chunks and UAE rule chunks.
6. Store only rebuildable projections in Weaviate: chunk text, embedding,
   metadata, and ids that point back to PostgreSQL and MinIO.
7. Implement hybrid search for clause retrieval.
8. Add an index rebuild script for both collections.
9. Add retrieval tests that check expected clause evidence appears in top-k
   results.
10. Update `README.md` service ports and `docs/architecture.md` topology.

## Final recommendation

Use **Weaviate** as the local vector database because native hybrid search is a
better match for OfferGuard's legal evidence retrieval.

Keep **pgvector** as the fallback if we decide the project should minimize
infrastructure and keep vectors inside PostgreSQL.

Keep the `VectorStore` adapter boundary so a future pgvector implementation can
be added without rewriting the Evidence Retrieval Agent.
