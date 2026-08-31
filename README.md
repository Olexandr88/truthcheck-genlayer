# TruthCheck — GenLayer Adjudication Registry

A frontend dApp for the **ClaimAdjudicator** Intelligent Contract deployed on GenLayer Studionet.

## Live demo

https://soft-seahorse-bc2ef8.netlify.app

## Deployed contract

`0xf79ad5032cad64E675321Dd2ed12FF59017a9fd4` https://explorer-studio.genlayer.com/address/0xf79ad5032cad64E675321Dd2ed12FF59017a9fd4

## What it does

TruthCheck lets anyone file a factual claim, attach a public source URL and a
standard of proof, and get a verdict (`true` / `false` / `undetermined`)
produced by GenLayer's validator consensus over an LLM read of that source.

Every claim also carries a separate **lifecycle status**, tracked
independently of the verdict:

```
pending --resolve()--> resolved --resolve() again, same verdict--> finalized
                          |
                          `--resolve() again, different verdict--> disputed
```

A single AI read of the evidence is only ever *provisional* (`resolved`).
A claim becomes `finalized` only once two resolutions in a row agree on
the same verdict; if a later resolution disagrees, the claim moves to
`disputed` instead of silently overwriting the earlier verdict. The
contract tracks this with two counters:

- `resolutions` — how many times `resolve()` has been called for that claim.
- `confirmations` — how many *consecutive* resolutions in a row agreed on
  the same verdict (resets to 1 whenever the verdict changes).

The frontend displays lifecycle status and verdict as two separate
elements on each case card — a status badge (`PENDING` / `RESOLVED` /
`FINALIZED` / `DISPUTED`) and, once a verdict exists, a stamp
(`TRUE` / `FALSE` / `UNDET.`) — since a claim can be `resolved` or
`disputed` with any verdict, the two are independent.

## How the frontend talks to GenLayer

The app (`index.html`) imports `genlayer-js` directly in the browser and
calls the deployed contract above:

| UI action                       | Contract function called                                         |
| -------------------------------- | ------------------------------------------------------------------ |
| Loading the docket on page load | `total_claims()` then `get_claim(id)` for each entry (read-only) |
| "File Claim" button             | `submit_claim(text, source_url, criteria)` (write, signed tx)    |
| "Resolve" / "Resolve again" button on a case card | `resolve(claim_id)` (write, signed tx)          |

Read calls use `readClient.readContract(...)`. Write calls generate a local
test account via `createAccount()`, then use `writeClient.writeContract(...)`
and `waitForTransactionReceipt(..., status: "FINALIZED")` to wait for
validator consensus before refreshing the UI. This is the same
account/funding pattern used by GenLayer Studio itself (test accounts
funded via the Studio faucet).

## Contract source

The `ClaimAdjudicator` contract source (Python, GenLayer SDK) was submitted
separately under the Intelligent Contracts category. It defines:

- `submit_claim(text, source_url, criteria) -> u32` — registers a new claim
  in the `pending` state.
- `resolve(claim_id) -> {claim_id, status, verdict, reasoning, confirmations}`
  — runs one round of the adjudication lifecycle described above. Uses a
  custom `leader_fn`/`validator_fn` equivalence check instead of
  `strict_eq`: validators must agree on `verdict` exactly, while
  `reasoning` only needs to be non-empty (since natural-language
  explanations legitimately vary between LLM runs).
- `get_claim(claim_id)` — returns `text`, `source_url`, `criteria`,
  `status`, `verdict`, `reasoning`, `resolutions`, `confirmations`.
- `total_claims()`

## Files

- `index.html` — the full frontend (HTML/CSS/JS, no build step). Open it
  directly or visit the live demo link above.
