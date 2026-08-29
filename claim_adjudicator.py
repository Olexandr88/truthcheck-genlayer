# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }

from genlayer import *
from dataclasses import dataclass

import typing


@allow_storage
@dataclass
class Claim:
    text: str
    source_url: str
    criteria: str
    status: str          # "pending" -> "resolved" -> "finalized" | "disputed"
    verdict: str          # "" | "true" | "false" | "undetermined"
    reasoning: str
    resolutions: u32       # how many times resolve() has run for this claim
    confirmations: u32     # consecutive matching resolutions in a row


class ClaimAdjudicator(gl.Contract):
    """
    A reusable claim-adjudication registry with an explicit lifecycle:

        pending --resolve()--> resolved --resolve() again, same verdict--> finalized
                                   |
                                   `--resolve() again, different verdict--> disputed (resolutions reset the streak)

    This models real dispute resolution: a single AI read of the evidence
    is provisional ("resolved"), not authoritative. A claim only becomes
    "finalized" once two independent resolutions in a row agree on the
    same verdict — protecting against a single noisy/adversarial run
    while still using GenLayer's own validator consensus (not a second
    off-chain check) to produce each individual resolution.

    Equivalence is custom, not strict_eq: validators must agree on the
    `verdict` field exactly; `reasoning` only needs to be non-empty, since
    natural-language phrasing legitimately varies between honest LLM runs
    reading the same evidence.
    """

    claims: TreeMap[u32, Claim]
    next_id: u32

    def __init__(self):
        self.next_id = u32(0)

    @gl.public.write
    def submit_claim(self, text: str, source_url: str, criteria: str) -> u32:
        """Registers a new claim in the "pending" state. Returns its id."""
        claim_id = self.next_id
        self.claims[claim_id] = Claim(
            text=text,
            source_url=source_url,
            criteria=criteria,
            status="pending",
            verdict="",
            reasoning="",
            resolutions=u32(0),
            confirmations=u32(0),
        )
        self.next_id = u32(self.next_id + 1)
        return claim_id

    @gl.public.write
    def resolve(self, claim_id: u32) -> typing.Any:
        """
        Runs one round of the adjudication lifecycle for a claim:

        1. The leader fetches the claim's evidence URL and asks the LLM
           for a structured verdict.
        2. Each validator independently repeats step 1 and accepts the
           leader's output only if their own verdict matches exactly
           (custom equivalence — see class docstring).
        3. The claim's state machine advances:
           - "pending"  -> "resolved"   (first resolution, provisional)
           - "resolved"/"disputed", same verdict as last time
                        -> confirmations += 1; "finalized" once
                           confirmations reaches 2
           - "resolved"/"finalized", different verdict this time
                        -> "disputed"; confirmations resets to 1
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
            return gl.nondet.exec_prompt(full_prompt, response_format="json")

        def validator_fn(leaders_res) -> bool:
            if not isinstance(leaders_res, gl.vm.Return):
                return False
            leader_out = leaders_res.calldata
            if "verdict" not in leader_out or "reasoning" not in leader_out:
                return False
            if not leader_out["reasoning"]:
                return False
            if leader_out["verdict"] not in ("true", "false", "undetermined"):
                return False

            my_result = leader_fn()
            if my_result.get("verdict") not in ("true", "false", "undetermined"):
                return False

            return my_result["verdict"] == leader_out["verdict"]

        result = gl.vm.run_nondet_unsafe(leader_fn, validator_fn)
        new_verdict = result["verdict"]

        previous_verdict = claim.verdict
        claim.resolutions = u32(claim.resolutions + 1)

        if claim.status == "pending":
            claim.status = "resolved"
            claim.confirmations = u32(1)
        elif new_verdict == previous_verdict:
            claim.confirmations = u32(claim.confirmations + 1)
            claim.status = "finalized" if claim.confirmations >= u32(2) else "resolved"
        else:
            claim.status = "disputed"
            claim.confirmations = u32(1)

        claim.verdict = new_verdict
        claim.reasoning = result["reasoning"]
        self.claims[claim_id] = claim

        return {
            "claim_id": claim_id,
            "status": claim.status,
            "verdict": claim.verdict,
            "reasoning": claim.reasoning,
            "confirmations": claim.confirmations,
        }

    @gl.public.view
    def get_claim(self, claim_id: u32) -> typing.Any:
        if claim_id not in self.claims:
            raise gl.vm.UserError("Unknown claim id")
        c = self.claims[claim_id]
        return {
            "text": c.text,
            "source_url": c.source_url,
            "criteria": c.criteria,
            "status": c.status,
            "verdict": c.verdict,
            "reasoning": c.reasoning,
            "resolutions": c.resolutions,
            "confirmations": c.confirmations,
        }

    @gl.public.view
    def total_claims(self) -> u32:
        return self.next_id
