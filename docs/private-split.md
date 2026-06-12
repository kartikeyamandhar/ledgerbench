# The private split protocol

A 30-item evaluation split lives in a **separate private repository**
(`ledgerbench-private`) and exists to detect contamination and overfitting on the
public bank (RT-004). The rules, stated once and enforced always:

1. **Never in this repository.** Not the items, not their ids, not their questions,
   not paraphrases — not in code, tests, fixtures, docs, commit messages, or issues.
   The gitleaks hook does not check semantics; authors do.
2. **Same standards.** The private items pass the same linter (`ledgerbench
   validate`), use the same contract, the same worlds, the same recipe-derived gold,
   and the same taxonomy discipline (one item, one failure class). Nothing about
   their construction differs except visibility.
3. **Aggregates only.** Published results show private-split numbers only as per-axis
   aggregates next to the public numbers. No per-item results, no failure-gallery
   entries, no verbatim traces from private items are ever published.
4. **Run locally.** Private-split runs execute on the maintainer's machine; result
   JSONL from private items is never committed to the public repo. The leaderboard
   carries the aggregate columns with a footnote pointing to this protocol.
5. **Divergence is the signal.** A large public-vs-private gap for an agent is
   evidence of contamination or format-tuning (RT-008), and is reported as such —
   that is the split's entire purpose.
6. **Rotation.** When the public bank rotates (v2), the private split rotates with
   it; retired private items may then be published as part of the public v2 bank.
