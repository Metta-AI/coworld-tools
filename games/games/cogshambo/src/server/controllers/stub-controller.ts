import type { CogAction, CogDecisionInput } from "../../shared/types.js";
import type { CogController } from "./cog-controller.js";

export class StubController implements CogController {
  async decide(_input: CogDecisionInput): Promise<CogAction> {
    return { type: "wait", intent: "observing" };
  }
}
