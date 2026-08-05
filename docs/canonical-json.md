# Canonical JSON policy

Research OS public contracts and `sha256_json` use canonical JSON policy version
1. The policy is a deliberately portable subset of JSON, not Python's default
`json.dumps` format.

- Object keys are sorted by UTF-16 code units, matching ECMAScript ordering.
- Strings and keys must contain Unicode scalar values. Unpaired UTF-16
  surrogates are rejected before UTF-8 encoding.
- Integers are limited to `[-9007199254740991, 9007199254740991]`, the range
  represented exactly by both Python integers and JavaScript numbers.
- Floats must be finite IEEE-754 binary64 values. They use ECMAScript's shortest
  round-trip spelling and fixed/exponent thresholds, including normalization of
  signed zero (`-0.0` becomes `0`) and integral floats (`1.0` becomes `1`).
- Large integral-looking numbers received over JSON are interpreted with
  JavaScript binary64 semantics; direct Python integers outside the safe range
  remain rejected so exact integer intent cannot be silently lost.
- JSON is compact UTF-8 with no insignificant whitespace.

For example, `0.3333333333333333`, `1e-7`, `1e20`, the smallest positive
binary64 value, and the largest finite binary64 value are supported. Non-finite
values and direct integers outside the safe range are rejected. Changing an
acceptance or encoding rule requires a new policy version and new
cross-language golden vectors.

Contract objects recursively detach and freeze JSON inputs after validation.
Their `to_dict()` methods always return a fresh ordinary dictionary/list tree,
so mutating an input, attribute view, or previous export cannot change later
serialization or provenance.
