# From Zero to GenLayer: Building a Claim Adjudication Oracle

A hands-on, multi-part tutorial that takes you from "what even is an
Intelligent Contract" to a deployed dApp with a working frontend — built
around a real project: **ClaimAdjudicator**, an oracle that resolves
factual claims ("did X happen?") by reading live web evidence and letting
a panel of AI validators agree on a verdict.

By the end you'll understand GenLayer's two core ideas — **Optimistic
Democracy** and the **Equivalence Principle** — not just as buzzwords, but
as the reason a contract like this can exist at all on a blockchain.

- Contract: `0xf79ad5032cad64E675321Dd2ed12FF59017a9fd4` ([explorer](https://explorer-studio.genlayer.com/address/0xf79ad5032cad64E675321Dd2ed12FF59017a9fd4))
- Full source + frontend: [github.com/Olexandr88/truthcheck-genlayer](https://github.com/Olexandr88/truthcheck-genlayer)
- Live demo: [soft-seahorse-bc2ef8.netlify.app](https://soft-seahorse-bc2ef8.netlify.app)

---

## Part 1 — Why GenLayer needs a different kind of consensus

Ordinary smart contracts are deterministic: given the same input, every
node must compute the exact same output, byte for byte. That's what lets
a network of strangers agree on the result without trusting each other.

It's also why traditional smart contracts can't natively ask "did this
event actually happen?" or "does this text satisfy these conditions?" —
questions like that don't have one universally reproducible answer. Two
honest computers reading the same news article, or calling the same LLM,
can come back with slightly different wording. A blockchain built on
strict byte-for-byte agreement would call that a failure.

GenLayer's answer is **Optimistic Democracy**: instead of requiring every
validator to compute an identical result, one validator (the *leader*)
proposes a result, and the rest independently check whether they'd have
reached a *comparable* conclusion. If enough validators agree the result
is acceptable, it's accepted — optimistically, the way a human court
accepts a jury's verdict without demanding every juror used identical
words in their reasoning.

That "comparable, not identical" check is the **Equivalence Principle**,
and it's the actual mechanism, not just a philosophy. It's a function you
write yourself.

---

## Part 2 — Setting up: GenLayer Studio

You don't need a wallet, a testnet faucet request, or any local
installation to start. Go to **studio.genlayer.com** — this is a
browser-based sandbox that simulates the full GenLayer network (leader,
validators, consensus) locally.

1. Open Studio. A test account is created for you automatically and
   pre-funded (you'll see a wallet address top-right).
2. In the file panel, click the "new file" icon and name it something
   like `claim_adjudicator.py`.
3. This is where we'll write the contract in Part 3.
4. The bottom panel ("Logs") shows every step of deployment and
   execution — leader proposals, validator votes, consensus results.
   Keep it open; it's the best way to actually *see* Optimistic
   Democracy happen.

If you'd rather work locally with `genlayer-js` and a CLI from the start,
you can fork the [GenLayer project boilerplate](https://github.com/genlayerlabs/genlayer-project-boilerplate)
instead — it gives you a preconfigured contract + frontend scaffold. This
tutorial builds the same shape of project from scratch so you understand
every piece.

---

## Part 3 — Writing the Intelligent Contract

### 3.1 Declaring state

Every file starts with a dependency header (pins the GenLayer SDK
version) and imports:

```python
# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }

from genlayer import *
import json
import typing
```

We want our contract to hold *many* claims, not just one — so instead of
a single set of fields, we define a storage-friendly record type and a
map of them:

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

    def __init__(self):
        self.next_id = u32(0)
```

`TreeMap[u32, Claim]` is GenLayer's on-chain dictionary type. Using a
registry like this — instead of one contract per claim — means a single
deployment can serve an entire application.

### 3.2 A plain write method: filing a claim

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

Nothing new here yet — this is deterministic, ordinary contract state, no
different from Solidity. The interesting part is next.

### 3.3 The nondeterministic write: resolving a claim

This is where GenLayer stops looking like a normal smart contract. We
want the contract to:

1. Fetch a real web page (nondeterministic — the page can change, and
   fetching it isn't something every node can verify byte-for-byte).
2. Ask an LLM to read it and decide true/false/undetermined
   (nondeterministic — LLM output isn't perfectly reproducible).
3. Only accept the result if enough validators reach a **comparable**
   conclusion.

```python
@gl.public.write
def resolve(self, claim_id: u32) -> typing.Any:
    if claim_id not in self.claims:
        raise gl.vm.UserError("Unknown claim id")

    claim = self.claims[claim_id]
    text, source_url, criteria = claim.text, claim.source_url, claim.criteria

    prompt = f"""You are a neutral fact-adjudicator for an on-chain oracle.

CLAIM:
{text}

RESOLUTION CRITERIA:
{criteria}

Decide TRUE, FALSE, or UNDETERMINED based on the evidence.
Respond with JSON only: {{"verdict": "...", "reasoning": "..."}}"""

    def leader_fn():
        response = gl.nondet.web.get(source_url)
        web_data = response.body.decode("utf-8")
        full_prompt = prompt + f"\n\nEVIDENCE:\n{web_data}"
        raw = gl.nondet.exec_prompt(full_prompt) \
            .replace("```json", "").replace("```", "").strip()
        return json.loads(raw)
```

`leader_fn` is what the leader validator runs: fetch the page, ask the
LLM, parse the JSON. Nothing here is guaranteed to be byte-identical
across runs — and that's fine, because it never gets compared
byte-for-byte.

### 3.4 Writing your own Equivalence Principle check

The simplest way to reach consensus on a nondeterministic result is
`gl.eq_principle.strict_eq`, which does demand an exact match. That's
appropriate for something like a number derived from a stable API. It's
*too strict* here: two truthful LLM calls can agree "TRUE" while phrasing
the reasoning differently, and `strict_eq` would wrongly reject that as
disagreement.

So instead we define our own comparison — a custom `validator_fn` that
only requires the parts that actually matter to match:

```python
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

Each validator independently re-fetches the same page, re-runs the same
prompt, and checks: *does my verdict match the leader's verdict?* The
`reasoning` field is only checked for being present and non-empty — not
compared. This is the Equivalence Principle in its most literal form:
you, the contract author, define what "equivalent" means for your use
case.

If the network can't agree, the transaction reverts — validators never
silently accept disagreement.

### 3.5 Storing the outcome and reading state back

```python
    claim.status = result["verdict"]
    claim.reasoning = result["reasoning"]
    if claim.status == "undetermined":
        claim.challenges = u32(claim.challenges + 1)
    self.claims[claim_id] = claim
    return {"claim_id": claim_id, "verdict": claim.status, "reasoning": claim.reasoning}

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

If a claim comes back `"undetermined"`, it stays open — `resolve()` can
be called again later once better evidence exists. `challenges` tracks
how many times that's happened.

### 3.6 Deploying in Studio

Paste the full contract into your file in Studio, click **Deploy**, watch
the Logs panel: you'll see `COMMITTING`, then per-validator
`execution finished` entries, then `Reached consensus` and `FINALIZED`.
That sequence *is* Optimistic Democracy running — a leader proposing, and
the group ratifying it.

Call `submit_claim(...)` with a real claim, a source URL, and criteria,
then call `resolve(0)`. Watch the logs again: this time you'll see
`gl.nondet.web.get` and the LLM call happen once per validator, and
consensus reached on the *verdict* despite the reasoning text differing
between them if you inspect it closely.

---

## Part 4 — The frontend: genlayer-js

A contract with no way to interact with it isn't a dApp. `genlayer-js`
lets a plain browser page talk to your deployed contract with no backend
server.

### 4.1 Reading state (no wallet needed)

```js
import { createClient } from "genlayer-js";

const readClient = createClient({ chain: STUDIO_CHAIN });

const total = await readClient.readContract({
  address: CONTRACT,
  functionName: "total_claims",
  args: [],
});

const claim = await readClient.readContract({
  address: CONTRACT,
  functionName: "get_claim",
  args: [i],
});
```

View functions cost nothing and need no signer — perfect for rendering a
list of existing claims on page load.

### 4.2 Writing state (signed transactions)

```js
import { createAccount } from "genlayer-js";

const account = createAccount();               // local test account
const writeClient = createClient({ chain: STUDIO_CHAIN, account });

const hash = await writeClient.writeContract({
  account,
  address: CONTRACT,
  functionName: "resolve",
  args: [claimId],
});

await writeClient.waitForTransactionReceipt({ hash, status: "FINALIZED" });
```

Two details matter here:

- `createAccount()` generates a fresh keypair client-side. On Studio it
  needs to be funded via the built-in faucet before it can send
  transactions — the same mechanism Studio itself uses when it
  auto-funds your session wallet.
- Waiting for `status: "FINALIZED"` — not just a submitted hash — is
  what guarantees validator consensus has actually completed before your
  UI shows a result. A hash alone only proves the transaction was
  broadcast, not that the network agreed on the outcome.

### 4.3 Putting it together

The full demo app renders a "docket" of every claim by looping
`0..total_claims()` and calling `get_claim` for each, offers a form that
calls `submit_claim`, and a button per claim that calls `resolve`. See
the complete, working `index.html` in the [repository](https://github.com/Olexandr88/truthcheck-genlayer)
— it's dependency-free beyond `genlayer-js` itself, so you can read the
whole data flow in one file.

---

## Part 5 — What to build next

`ClaimAdjudicator` is deliberately general — the claim, its source, and
its resolution criteria are all runtime parameters, not hardcoded. That
means the same deployed contract can back very different apps:

- **Prediction markets** — claims become market questions, `resolve()`
  becomes the settlement call.
- **Dispute resolution** — two parties file conflicting claims about the
  same agreement; criteria encode the contract terms.
- **Content moderation / fact-checking feeds** — claims are user
  submissions, source_url is the flagged content.

The pattern to take away isn't "how to check facts" — it's: **identify
the nondeterministic step your idea needs (a web read, an LLM judgment,
an API call), isolate it in a `leader_fn`, and write a `validator_fn`
that expresses exactly what "agreement" means for your problem.** That's
the whole shape of building on GenLayer.

---

## Recap

- **Optimistic Democracy**: a leader proposes, validators ratify —
  contracts don't need byte-identical computation to reach consensus.
- **Equivalence Principle**: *you* define what counts as agreement, via
  `strict_eq` for simple cases or a custom `validator_fn` when only part
  of a result needs to match.
- **Studio** gives you the full consensus flow locally, with logs that
  make the leader/validator exchange visible.
- **genlayer-js** talks to a deployed contract with plain reads for view
  functions and signed writes (waited on until `FINALIZED`) for anything
  that changes state.

Full source for both the contract and the frontend: [github.com/Olexandr88/truthcheck-genlayer](https://github.com/Olexandr88/truthcheck-genlayer)
