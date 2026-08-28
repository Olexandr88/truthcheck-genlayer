# Building a Multi-Claim Adjudication Oracle on GenLayer

A walkthrough of **ClaimAdjudicator** — a reusable Intelligent Contract that
resolves factual claims against live web evidence using validator
consensus, plus the frontend that drives it.

- Contract: `0xf79ad5032cad64E675321Dd2ed12FF59017a9fd4` ([explorer](https://explorer-studio.genlayer.com/address/0xf79ad5032cad64E675321Dd2ed12FF59017a9fd4))
- Frontend + source: [github.com/Olexandr88/truthcheck-genlayer](https://github.com/Olexandr88/truthcheck-genlayer)
- Live demo: [soft-seahorse-bc2ef8.netlify.app](https://soft-seahorse-bc2ef8.netlify.app)

## 1. The problem

Most "AI oracle" demos hardcode one claim and one prompt. That's fine for a
tutorial, but it isn't reusable: every new use case means redeploying a new
contract. `ClaimAdjudicator` instead keeps a **registry** of claims, so a
single deployment can back an entire application — a prediction market, a
dispute-resolution tool, a fact-checking feed — for any number of claims.

## 2. Contract state

```python
@allow_storage
class Claim:
    text: str
    source_url: str
    criteria: str
    status: str      # "pending" | "true" | "false" | "undetermined"
    reasoning: str
    challenges: u32

class ClaimAdjudicator(gl.Contract):
    claims: TreeMap[u32, Claim]
    next_id: u32
```

Each claim carries its own evidence source and its own resolution
criteria, so the same contract can adjudicate completely unrelated
questions without redeploying.

## 3. Filing a claim

```python
@gl.public.write
def submit_claim(self, text: str, source_url: str, criteria: str) -> u32:
    claim_id = self.next_id
    self.claims[claim_id] = Claim(
        text=text, source_url=source_url, criteria=criteria,
        status="pending", reasoning="", challenges=u32(0),
    )
    self.next_id = u32(self.next_id + 1)
    return claim_id
```

This is a plain write — no LLM call yet. The evidence and criteria are
just stored so any validator can independently re-derive the same verdict
later.

## 4. Resolving a claim: custom equivalence

The interesting part is `resolve()`. A naive approach runs one prompt and
uses `gl.eq_principle.strict_eq`, which requires every validator's output
to match **character for character**. That's too strict for natural
language: two honest LLM runs can agree on the verdict and still phrase
the reasoning differently.

Instead, `ClaimAdjudicator` defines its own leader/validator functions:

```python
def leader_fn():
    response = gl.nondet.web.get(source_url)
    web_data = response.body.decode("utf-8")
    raw = gl.nondet.exec_prompt(full_prompt) \
        .replace("```json", "").replace("```", "").strip()
    return json.loads(raw)

def validator_fn(leaders_res) -> bool:
    if not isinstance(leaders_res, gl.vm.Return):
        return False
    leader_out = leaders_res.calldata
    if "verdict" not in leader_out or "reasoning" not in leader_out:
        return False
    if not leader_out["reasoning"]:
        return False
    my_result = leader_fn()
    return my_result["verdict"] == leader_out["verdict"]

result = gl.vm.run_nondet_unsafe(leader_fn, validator_fn)
```

The leader fetches the source and asks the LLM for a structured verdict.
Each validator independently repeats the same fetch-and-prompt, then
accepts the leader's result **only if their own verdict matches exactly**
— `reasoning` just has to be non-empty. This models how real adjudication
works: the *decision* needs consensus, the *explanation* doesn't need to
be identical wording.

If the result comes back `"undetermined"`, the claim stays open and its
`challenges` counter increments, so `resolve()` can be called again later
once better evidence is available.

## 5. Reading state

```python
@gl.public.view
def get_claim(self, claim_id: u32) -> typing.Any:
    c = self.claims[claim_id]
    return {"text": c.text, "source_url": c.source_url,
            "status": c.status, "reasoning": c.reasoning,
            "challenges": c.challenges}

@gl.public.view
def total_claims(self) -> u32:
    return self.next_id
```

Two read-only views are enough to drive an entire frontend docket: iterate
`0..total_claims()` and call `get_claim` for each.

## 6. Wiring up a frontend with GenLayerJS

The demo app imports `genlayer-js` directly in the browser (no build
step) and talks to the contract above:

```js
import { createClient, createAccount } from "genlayer-js";

const readClient = createClient({ chain: STUDIO_CHAIN });

const total = await readClient.readContract({
  address: CONTRACT, functionName: "total_claims", args: [],
});

const claim = await readClient.readContract({
  address: CONTRACT, functionName: "get_claim", args: [i],
});
```

Reads need no signer. Writes (`submit_claim`, `resolve`) use a locally
generated test account, funded via the Studio faucet, then:

```js
const account = createAccount();
const writeClient = createClient({ chain: STUDIO_CHAIN, account });

const hash = await writeClient.writeContract({
  account, address: CONTRACT, functionName: "resolve", args: [claimId],
});
await writeClient.waitForTransactionReceipt({ hash, status: "FINALIZED" });
```

Waiting for `FINALIZED` (not just a submitted hash) matters: it means
validator consensus has actually been reached before the UI refreshes and
shows a verdict.

## 7. Takeaways for your own Intelligent Contracts

- **Registries beat singletons.** A `TreeMap` of items backed by one
  contract is almost always more reusable than one contract per item.
- **Write your own equivalence check when `strict_eq` is too strict.**
  Natural-language outputs need semantic agreement, not byte-identical
  agreement — decide which *fields* must match and which can vary.
- **Separate write-then-resolve.** Filing a claim and adjudicating it are
  different operations with different costs; splitting them lets the
  expensive LLM/web step run only when actually needed.
- **`FINALIZED`, not just a tx hash**, is the signal your frontend should
  wait on before trusting a result.

Full source for both the contract and the frontend is in the linked
repository.
