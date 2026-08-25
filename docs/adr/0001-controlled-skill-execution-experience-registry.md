# Use a controlled registry for Skill execution experiences

Business Skills declare an execution-experience key, and the platform maps that key through a reviewed allowlist to platform-owned UI code. External Skill packages cannot load arbitrary React components, and a published business Skill without a registered experience is blocked from execution instead of falling back to the generic file-and-parameter form; this preserves deployment security and makes each business workflow explicit at the cost of requiring a platform change when a new experience is introduced.
