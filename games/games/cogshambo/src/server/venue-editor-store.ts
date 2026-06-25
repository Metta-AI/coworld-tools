import type { VenueEditorState } from "../shared/types.js";
import {
  defaultVenueGraphPath,
  readVenueGraphFile,
  VENUE_EDITOR_IMAGE_URL,
  writeVenueGraphFile,
} from "./venue-graph.js";

export { defaultVenueGraphPath, VENUE_EDITOR_IMAGE_URL };

export type VenueEditorStore = {
  load(seed: () => Omit<VenueEditorState, "updatedAt">): VenueEditorState;
  save(state: Omit<VenueEditorState, "updatedAt">): VenueEditorState;
  close(): void;
};

export function createJsonVenueEditorStore(filePath = defaultVenueGraphPath()): VenueEditorStore {
  return {
    load(seed) {
      return readVenueGraphFile(filePath, seed);
    },
    save(state) {
      return writeVenueGraphFile(state, filePath);
    },
    close() {
      // JSON venue storage does not hold open resources.
    },
  };
}
