# TruthCheck — GenLayer Adjudication Registry

A frontend dApp for the **ClaimAdjudicator** Intelligent Contract deployed on GenLayer Studionet.

## Live demo
https://soft-seahorse-bc2ef8.netlify.app

## Deployed contract
`0xf79ad5032cad64E675321Dd2ed12FF59017a9fd4`
https://explorer-studio.genlayer.com/address/0xf79ad5032cad64E675321Dd2ed12FF59017a9fd4

## What it does

TruthCheck lets anyone file a factual claim, attach a public source URL and a
standard of proof, and get a verdict (`true` / `false` / `undetermined`)
produced by GenLayer's validator consensus over an LLM read of that source.

## How the frontend talks to GenLayer

The app (`index.html`) imports `genlayer-js` directly in the browser and
calls the deployed contract above:

| UI action | Contract function called |
|---|---|
| Loading the docket on page load | `total_claims()` then `get_claim(id)` for each entry (read-only) |
| "File Claim" button | `submit_claim(text, source_url, criteria)` (write, signed tx) |
| "Resolve" button on a case card | `resolve(claim_id)` (write, signed tx) |

Read calls use `readClient.readContract(...)`. Write calls generate a local
test account via `createAccount()`, then use
`writeClient.writeContract(...)` and `waitForTransactionReceipt(...,
status: "FINALIZED")` to wait for validator consensus before refreshing the
UI. This is the same account/funding pattern used by GenLayer Studio itself
(test accounts funded via the Studio faucet).

## Contract source

The `ClaimAdjudicator` contract source (Python, GenLayer SDK) was submitted
separately under the Intelligent Contracts category. It defines:

- `submit_claim(text, source_url, criteria) -> u32`
- `resolve(claim_id) -> {verdict, reasoning}` — uses a custom
  `leader_fn`/`validator_fn` equivalence check instead of `strict_eq`:
  validators must agree on `verdict` exactly, while `reasoning` only needs
  to be non-empty (since natural-language explanations legitimately vary
  between LLM runs).
- `get_claim(claim_id)`, `total_claims()`

## Files

- `index.html` — the full frontend (HTML/CSS/JS, no build step). Open it
  directly or visit the live demo link above.
