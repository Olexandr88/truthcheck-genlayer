# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }

from genlayer import *

import json
import typing


@allow_storage
class Claim:
    text: str
    source_url: str
    criteria: str
    status: str      # "pending" | "true" | "false" | "undetermined"
    reasoning: str
    challenges: u32   # how many times this claim was re-resolved


class ClaimAdjudicator(gl.Contract):
    """
    A multi-claim adjudication oracle.

    Unlike a single-shot demo contract, this one manages a registry of
    independent claims (each with its own evidence source and resolution
    criteria), supports re-resolution when a result is disputed, and uses
    a custom equivalence function: validators must agree on the verdict
    field exactly, but reasoning text is allowed to differ in wording as
    long as it is non-empty. This mirrors how real adjudication needs to
    work — the *decision* must reach consensus, the *explanation* doesn't
    need to be character-identical across LLM runs.

    Real use case: a prediction market, bounty platform, or insurance
    dApp registers claims here and reads back structured verdicts, instead
    of every application reimplementing its own oracle logic from scratch.
    """

    claims: TreeMap[u32, Claim]
    next_id: u32

    def __init__(self):
        self.next_id = u32(0)

    @gl.public.write
    def submit_claim(self, text: str, source_url: str, criteria: str) -> u32:
        """
        Registers a new claim to be adjudicated later. Returns its id.
        """
        claim_id = self.next_id
        self.claims[claim_id] = Claim(
            text=text,
            source_url=source_url,
            criteria=criteria,
            status="pending",
            reasoning="",
            challenges=u32(0),
        )
        self.next_id = u32(self.next_id + 1)
        return claim_id

    @gl.public.write
    def resolve(self, claim_id: u32) -> typing.Any:
        """
        Fetches evidence for the given claim and reaches validator
        consensus on the verdict using a custom equivalence check:
        the leader proposes {verdict, reasoning}; each validator
        independently re-runs the same prompt and accepts the leader's
        result only if their own verdict matches exactly. Reasoning is
        checked only for presence, not exact wording, since natural
        language explanations legitimately vary between LLM runs.
        """
        if claim_id not in self.claims:
            raise gl.vm.UserError("Unknown claim id")

        claim = self.claims[claim_id]
        text = claim.text
        source_url = claim.source_url
        criteria = claim.criteria

        prompt = f"""You are a neutral fact-adjudicator for an on-chain oracle.

CLAIM:
{text}

RESOLUTION CRITERIA:
{criteria}

Fetch and read the following evidence, then decide whether the claim is
TRUE, FALSE, or UNDETERMINED (if there isn't enough information yet).

Respond with JSON only:
{{"verdict": "true" | "false" | "undetermined", "reasoning": "one short sentence"}}
No markdown, no extra text — the response must be parsable as JSON."""

        def leader_fn():
            response = gl.nondet.web.get(source_url)
            web_data = response.body.decode("utf-8")
            full_prompt = prompt + f"\n\nEVIDENCE:\n{web_data}"
            raw = (
                gl.nondet.exec_prompt(full_prompt)
                .replace("```json", "")
                .replace("```", "")
                .strip()
            )
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

        claim.status = result["verdict"]
        claim.reasoning = result["reasoning"]
        if claim.status == "undetermined":
            claim.challenges = u32(claim.challenges + 1)
        self.claims[claim_id] = claim

        return {"claim_id": claim_id, "verdict": claim.status, "reasoning": claim.reasoning}

    @gl.public.view
    def get_claim(self, claim_id: u32) -> typing.Any:
        if claim_id not in self.claims:
            raise gl.vm.UserError("Unknown claim id")
        c = self.claims[claim_id]
        return {
            "text": c.text,
            "source_url": c.source_url,
            "status": c.status,
            "reasoning": c.reasoning,
            "challenges": c.challenges,
        }

    @gl.public.view
    def total_claims(self) -> u32:
        return self.next_id
