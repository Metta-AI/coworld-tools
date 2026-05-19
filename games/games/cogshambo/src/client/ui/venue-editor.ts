import type { Position, VenueEditorState, VenueRect, VenueRoom, VenueRoomPath, VenueSpot } from "../../shared/types";
import type { VenueEditorStateResponse } from "../../shared/protocol";
import { escapeHtml } from "./html";
import {
  addRoomPathPoint,
  assignSelectedSpotsToRoom,
  copySelectedSpots,
  createRoom,
  deleteRoomPath,
  deleteRoomPathPoint,
  moveRoomPathPoint,
  moveRoomRect,
  pasteCopiedSpots,
  pasteCopiedSpotsIntoRoom,
  resizeRoomRect,
  roomRect,
  toggleSpotRoomAssignment,
  toggleSelectedSpotRoles,
  upsertRoomPath,
  type VenueEditorClipboard,
  type VenueEditorDraft,
} from "./venue-editor-state";

type DragState = {
  pointerId: number;
  origin: Position;
  startPositions: Map<string, Position>;
  moved: boolean;
};
type RoomDragState = {
  pointerId: number;
  roomId: string;
  origin: Position;
  startRect: VenueRect;
  moved: boolean;
};
type RoomResizeState = RoomDragState;
type PathPointDragState = {
  pointerId: number;
  pathId: string;
  pointIndex: number;
  origin: Position;
  startPosition: Position;
  moved: boolean;
};
type MapPanState = {
  pointerId: number;
  startClient: Position;
  startPan: Position;
};
type ConnectDragState = {
  pointerId: number;
  fromRoomId: string;
  fromPosition: Position;
  currentPosition: Position;
};
type BoardViewport = {
  pan: Position;
  zoom: number;
};
type EditorMode = "room" | "spot" | "path";
type FocusSnapshot = {
  kind: "room-name";
  roomId: string;
  value: string;
  selectionStart: number | null;
  selectionEnd: number | null;
};

const MAX_ZOOM = 4;
const MIN_ZOOM = 0.75;
const SPOT_RADIUS = 0.38;
const PASTE_OFFSET: Position = { x: 2, y: 2 };
const WHEEL_ZOOM_SPEED = 0.0015;
const AUTOSAVE_DELAY_MS = 150;

export type VenueEditorMountOptions = {
  embedded?: boolean;
};

export function mountVenueEditor(app: HTMLElement, options: VenueEditorMountOptions = {}): () => void {
  const editor = new VenueEditor(app, options);
  void editor.load();
  return () => editor.dispose();
}

class VenueEditor {
  private readonly abortController = new AbortController();
  private draft: VenueEditorDraft | undefined;
  private selectedSpotIds = new Set<string>();
  private selectedRoomId: string | undefined;
  private activeRoomId: string | undefined;
  private connectTargetRoomId: string | undefined;
  private hoverRoomId: string | undefined;
  private hoverPathId: string | undefined;
  private selectedPathId: string | undefined;
  private selectedPathPointIndex: number | undefined;
  private pathEditing = false;
  private primarySelectedSpotId: string | undefined;
  private clipboard: VenueEditorClipboard | undefined;
  private dragState: DragState | undefined;
  private roomDragState: RoomDragState | undefined;
  private roomResizeState: RoomResizeState | undefined;
  private pathPointDragState: PathPointDragState | undefined;
  private mapPanState: MapPanState | undefined;
  private connectDragState: ConnectDragState | undefined;
  private boardViewport: BoardViewport = { zoom: 1, pan: { x: 0, y: 0 } };
  private lastBoardPointerPosition: Position | undefined;
  private editorMode: EditorMode = "room";
  private lastRoomClick: { roomId: string; timeStamp: number } | undefined;
  private suppressNextClick = false;
  private suppressNextRoomClick = false;
  private saveStatus = "Loading";
  private dirty = false;
  private dirtyRevision = 0;
  private autosaveTimer: number | undefined;
  private disposed = false;

  constructor(
    private readonly app: HTMLElement,
    private readonly options: VenueEditorMountOptions,
  ) {
    if (!this.options.embedded) {
      document.body.classList.add("venue-editor-body");
    }
    window.addEventListener("keydown", (event) => this.handleKeyDown(event), { signal: this.abortController.signal });
  }

  dispose(): void {
    this.disposed = true;
    this.abortController.abort();
    if (this.autosaveTimer !== undefined) {
      window.clearTimeout(this.autosaveTimer);
      this.autosaveTimer = undefined;
    }
    if (!this.options.embedded) {
      document.body.classList.remove("venue-editor-body");
    }
  }

  async load(): Promise<void> {
    this.render();
    try {
      const response = await fetch("/api/venue-editor");
      if (!response.ok) {
        throw new Error(`${response.status} ${response.statusText}`);
      }

      const body = await response.json() as VenueEditorStateResponse;
      this.draft = stripUpdatedAt(body.state);
      this.saveStatus = body.state.updatedAt ? `Saved ${formatSavedAt(body.state.updatedAt)}` : "Seeded";
    } catch (error) {
      this.saveStatus = `Load failed: ${compactError(error)}`;
    }
    this.render();
  }

  private render(): void {
    if (this.disposed) {
      return;
    }
    const focusedControl = this.captureFocusedControl();

    if (!this.draft) {
      this.app.className = this.appClassName();
      this.app.innerHTML = `
        <main class="${this.mainClassName()}" aria-label="Venue editor">
          <header class="venue-editor-toolbar">
            <h1>Venue Editor</h1>
            <span class="venue-editor-status">${escapeHtml(this.saveStatus)}</span>
          </header>
        </main>
      `;
      return;
    }

    const selectedCount = this.selectedSpotIds.size;
    const activeRoom = this.activeRoomId ? this.roomForId(this.activeRoomId) : undefined;
    const isSpotSelectionActive = activeRoom || this.editorMode === "spot" || (this.selectedRoomId && selectedCount > 0);
    const selectedSummary = isSpotSelectionActive
      ? selectedCount === 1 ? "1 spot selected" : `${selectedCount} spots selected`
      : this.connectTargetRoomId
        ? "2 rooms selected"
        : this.selectedRoomId
          ? "1 room selected"
          : "No room selected";
    this.app.className = this.appClassName();
    this.app.innerHTML = `
      <main class="${this.mainClassName()}" aria-label="Venue editor">
        <header class="venue-editor-toolbar">
          <div class="venue-editor-title">
            <h1>${activeRoom ? "Room Editor" : "Venue Editor"}</h1>
            ${activeRoom ? `<span>${escapeHtml(activeRoom.label)}</span>` : `<span>${this.draft.rooms.length} rooms</span>`}
            <span>${this.visibleSpots().length} spots</span>
            <span>${selectedSummary}</span>
          </div>
          ${this.renderShortcutStrip()}
          <div class="venue-editor-actions">
            ${!activeRoom && this.editorMode === "room" ? `<button class="hud-button" type="button" data-action="create-room">Create Room</button>` : ""}
            ${activeRoom ? "" : this.renderModeToggle()}
            <span class="venue-editor-status ${this.dirty ? "is-dirty" : ""}">${escapeHtml(this.saveStatus)}</span>
            ${activeRoom ? `<button class="hud-button hud-button-secondary" type="button" data-action="exit-room-editor">Back</button>` : ""}
            <button class="hud-button hud-button-secondary" type="button" data-action="clear-selection">Clear</button>
          </div>
        </header>
        <section class="venue-editor-workspace">
          ${this.renderBoard()}
          ${this.renderSelectedRoomPanel()}
          ${this.renderSelectedPathPanel()}
        </section>
      </main>
    `;
    this.bindEvents();
    this.restoreFocusedControl(focusedControl);
  }

  private renderShortcutStrip(): string {
    const shortcuts = [
      ["Cmd-N", "New room"],
      ["Cmd-X", "Cut spots"],
      ["Cmd-S", "Toggle spot"],
      ["Cmd-C", "Copy spots"],
      ["Cmd-V", "Paste spots"],
      ["Delete", "Delete selection"],
      ["Esc", "Clear/back"],
      ["Double-click on room", "Edit room"],
      ["Double-click on spot", "Participant/Audience"],
    ] as const;

    return `
      <div class="venue-editor-shortcuts" aria-label="Venue editor shortcuts">
        ${shortcuts.map(([shortcut, label]) => `
          <span class="venue-editor-shortcut">
            <kbd>${escapeHtml(shortcut)}</kbd>
            <span>${escapeHtml(label)}</span>
          </span>
        `).join("")}
      </div>
    `;
  }

  private renderModeToggle(): string {
    return `
      <div class="venue-editor-mode-toggle" aria-label="Venue editor mode">
        <button
          class="hud-button hud-button-secondary ${this.editorMode === "room" ? "is-active" : ""}"
          type="button"
          data-action="set-editor-mode"
          data-editor-mode="room"
          aria-pressed="${this.editorMode === "room" ? "true" : "false"}"
        >Room Mode</button>
        <button
          class="hud-button hud-button-secondary ${this.editorMode === "spot" ? "is-active" : ""}"
          type="button"
          data-action="set-editor-mode"
          data-editor-mode="spot"
          aria-pressed="${this.editorMode === "spot" ? "true" : "false"}"
        >Spot Mode</button>
        <button
          class="hud-button hud-button-secondary ${this.editorMode === "path" ? "is-active" : ""}"
          type="button"
          data-action="set-editor-mode"
          data-editor-mode="path"
          aria-pressed="${this.editorMode === "path" ? "true" : "false"}"
        >Path Mode</button>
      </div>
    `;
  }

  private appClassName(): string {
    return `venue-editor-app${this.options.embedded ? " venue-editor-app-embedded" : ""}`;
  }

  private mainClassName(): string {
    return `venue-editor${this.options.embedded ? " venue-editor-embedded" : ""}`;
  }

  private renderBoard(): string {
    if (!this.draft) {
      return "";
    }

    const visibleSpots = this.visibleSpots();
    const spotMarkup = visibleSpots.map((spot) => this.renderSpot(spot)).join("");
    const roomMarkup = this.activeRoomId ? "" : this.renderRooms();
    const pathMarkup = !this.activeRoomId && this.canEditPathsInOverview()
      ? this.renderRoomPaths()
      : "";
    const boardClass = [
      "venue-editor-board",
      this.activeRoomId ? "is-room-editor" : "is-venue-overview",
      !this.activeRoomId ? `is-${this.editorMode}-mode` : "",
    ].filter(Boolean).join(" ");

    return `
      <div class="venue-editor-board-shell" data-board-shell>
        <div
          class="${boardClass}"
          data-board
          data-pan-x="${this.boardViewport.pan.x.toFixed(1)}"
          data-pan-y="${this.boardViewport.pan.y.toFixed(1)}"
          data-zoom="${this.boardViewport.zoom.toFixed(3)}"
          style="${this.boardStyle()}"
        >
          <img class="venue-editor-image" src="${escapeHtml(this.draft.imageUrl)}" alt="Current venue floor plan" draggable="false" />
          ${pathMarkup}
          ${roomMarkup}
          <div class="venue-spot-layer">
            ${spotMarkup}
          </div>
        </div>
      </div>
    `;
  }

  private renderRooms(): string {
    if (!this.draft) {
      return "";
    }

    const roomMarkup = this.draft.rooms.map((room) => {
      const rect = this.roomRectFor(room);
      const selectedClass = this.selectedRoomId === room.id ? " is-selected" : "";
      const targetClass = this.connectTargetRoomId === room.id ? " is-connect-target" : "";
      const connectHandleMarkup = this.editorMode === "path"
        ? `<button
            class="venue-room-connect-handle"
            type="button"
            data-path-connect-room-id="${escapeHtml(room.id)}"
            aria-label="Create path from ${escapeHtml(room.label)}"
            title="Create path from ${escapeHtml(room.label)}"
          >+</button>`
        : "";
      return `<div
        class="venue-room-rect${selectedClass}${targetClass}"
        role="button"
        tabindex="0"
        data-room-id="${escapeHtml(room.id)}"
        data-rect="${formatRect(rect)}"
        style="left: ${rectPercentX(rect, this.draft!).toFixed(3)}%; top: ${rectPercentY(rect, this.draft!).toFixed(3)}%; width: ${rectPercentWidth(rect, this.draft!).toFixed(3)}%; height: ${rectPercentHeight(rect, this.draft!).toFixed(3)}%;"
        aria-label="${escapeHtml(`${room.label} (${room.id})`)}"
        title="${escapeHtml(room.label)}"
      >
        <span class="venue-room-rect-label">${escapeHtml(room.label)}</span>
        ${connectHandleMarkup}
        ${selectedClass ? `<span class="venue-room-resize-handle" data-room-resize-room-id="${escapeHtml(room.id)}" aria-label="Resize ${escapeHtml(room.label)}"></span>` : ""}
      </div>`;
    }).join("");

    return `
      <div class="venue-room-rect-layer" data-room-layer>
        ${roomMarkup}
      </div>
    `;
  }

  private renderRoomPaths(): string {
    if (!this.draft) {
      return "";
    }

    const pathMarkup = this.draft.paths.map((path) => {
      const points = this.roomPathPoints(path);
      if (points.length < 2) {
        return "";
      }

      const pointsAttribute = escapeHtml(
        points.map((point) => `${pointPercentX(point, this.draft!).toFixed(3)},${pointPercentY(point, this.draft!).toFixed(3)}`).join(" "),
      );
      const className = [
        "venue-room-path",
        this.selectedPathId === path.id ? "is-selected" : "",
        this.pathEditing && this.selectedPathId === path.id ? "is-editing" : "",
        this.isRoomConnectedPath(path) ? "is-room-connected" : "",
        this.hoverPathId === path.id ? "is-hovered" : "",
      ].filter(Boolean).join(" ");
      return `
        <polyline
          class="${className}"
          data-room-path="${escapeHtml(path.id)}"
          data-from-room-id="${escapeHtml(path.fromRoomId)}"
          data-to-room-id="${escapeHtml(path.toRoomId)}"
          points="${pointsAttribute}"
        />
        <polyline
          class="venue-room-path-hit"
          data-room-path-hit="${escapeHtml(path.id)}"
          points="${pointsAttribute}"
        />`;
    }).join("");
    const pointMarkup = this.pathEditing && this.selectedPathId
      ? (this.draft.paths.find((path) => path.id === this.selectedPathId)?.points ?? []).map((point, index) => `
          <button
            class="venue-path-point${this.selectedPathPointIndex === index ? " is-selected" : ""}"
            type="button"
            data-path-id="${escapeHtml(this.selectedPathId!)}"
            data-path-point-index="${index}"
            data-position="${formatPosition(point)}"
            style="left: ${pointPercentX(point, this.draft!).toFixed(3)}%; top: ${pointPercentY(point, this.draft!).toFixed(3)}%;"
            aria-label="Path waypoint ${index + 1}"
          ></button>
        `).join("")
      : "";

    const previewMarkup = this.connectDragState
      ? `<polyline
          class="venue-room-path venue-room-path-preview"
          points="${escapeHtml([
            `${pointPercentX(this.connectDragState.fromPosition, this.draft).toFixed(3)},${pointPercentY(this.connectDragState.fromPosition, this.draft).toFixed(3)}`,
            `${pointPercentX(this.connectDragState.currentPosition, this.draft).toFixed(3)},${pointPercentY(this.connectDragState.currentPosition, this.draft).toFixed(3)}`,
          ].join(" "))}"
        />`
      : "";

    return `
      <svg class="venue-room-path-layer" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
        ${pathMarkup}
        ${previewMarkup}
      </svg>
      <div class="venue-path-point-layer">
        ${pointMarkup}
      </div>
    `;
  }

  private renderSelectedRoomPanel(): string {
    if (!this.draft || this.activeRoomId || this.editorMode !== "room" || !this.selectedRoomId) {
      return "";
    }

    const room = this.roomForId(this.selectedRoomId);
    if (!room) {
      return "";
    }

    const targetRoom = this.connectTargetRoomId ? this.roomForId(this.connectTargetRoomId) : undefined;
    const selectedRoomSpotCount = this.selectedSpotIdsInRoom(room.id).size;
    const roomSpots = this.roomSpots(room.id);
    const participantSpotCount = roomSpots.filter((spot) => (spot.role ?? "speaker") === "speaker").length;
    const audienceSpotCount = roomSpots.length - participantSpotCount;
    const connectedRooms = this.connectedRoomsForRoom(room.id);
    const connectButton = targetRoom
      ? `<button
          class="hud-button"
          type="button"
          data-action="connect-rooms"
          data-from-room-id="${escapeHtml(room.id)}"
          data-to-room-id="${escapeHtml(targetRoom.id)}"
        >Create Path</button>`
      : "";
    return `
      <aside
        class="venue-selected-room-panel"
        data-selected-room-panel
        data-selected-room-panel-room-id="${escapeHtml(room.id)}"
        aria-label="Selected room controls"
      >
        <div class="venue-selected-room-header">
          <label class="venue-room-name-field">
            <span>Name</span>
            <input
              type="text"
              value="${escapeHtml(room.label)}"
              data-room-name-input
              data-room-name-room-id="${escapeHtml(room.id)}"
              aria-label="Room name"
            />
          </label>
          <span>${escapeHtml(room.id)}</span>
        </div>
        <div class="venue-selected-room-meta">
          <span>${room.spotIds.length} spots</span>
          <span>${participantSpotCount} participants</span>
          <span>${audienceSpotCount} audience</span>
          <span>${selectedRoomSpotCount} selected</span>
          ${targetRoom ? `<span>Target: ${escapeHtml(targetRoom.label)}</span>` : ""}
        </div>
        <div class="venue-connected-rooms" data-connected-rooms-list>
          <span class="venue-panel-section-title">Connected Rooms</span>
          ${
            connectedRooms.length
              ? connectedRooms.map(({ room: connectedRoom, path }) => `
                  <div
                    class="venue-connected-room-row${this.hoverPathId === path.id ? " is-path-hovered" : ""}"
                    data-connected-room-id="${escapeHtml(connectedRoom.id)}"
                    data-connected-room-path-id="${escapeHtml(path.id)}"
                  >
                    <span class="venue-connected-room-label">${escapeHtml(connectedRoom.label)}</span>
                    <span>${path.points.length} waypoints</span>
                    <button
                      class="venue-connected-room-remove"
                      type="button"
                      data-action="delete-connected-room-path"
                      data-room-path-id="${escapeHtml(path.id)}"
                      aria-label="Remove link to ${escapeHtml(connectedRoom.label)}"
                    >[x]</button>
                  </div>
                `).join("")
              : `<div class="venue-connected-room-empty">No connected rooms</div>`
          }
        </div>
        <div class="venue-selected-room-actions">
          ${connectButton}
          <button class="hud-button" type="button" data-action="add-room-spot" data-room-panel-room-id="${escapeHtml(room.id)}">Add Spot</button>
          <button class="hud-button hud-button-secondary" type="button" data-action="copy-selected-spots" ${selectedRoomSpotCount > 0 ? "" : "disabled"}>Copy</button>
          <button class="hud-button hud-button-secondary" type="button" data-action="paste-room-spots" ${this.clipboard?.spots.length ? "" : "disabled"}>Paste</button>
          <button class="hud-button hud-button-secondary" type="button" data-action="delete-selected-spots" ${selectedRoomSpotCount > 0 ? "" : "disabled"}>Delete</button>
        </div>
      </aside>
    `;
  }

  private renderSelectedPathPanel(): string {
    if (!this.draft || this.activeRoomId || !this.canEditPathsInOverview() || !this.selectedPathId) {
      return "";
    }

    const path = this.draft.paths.find((candidate) => candidate.id === this.selectedPathId);
    if (!path) {
      return "";
    }

    return `
      <aside
        class="venue-selected-room-panel venue-selected-path-panel"
        data-selected-path-panel
        data-selected-path-id="${escapeHtml(path.id)}"
        aria-label="Selected path controls"
      >
        <div class="venue-selected-room-header">
          <span class="venue-panel-section-title">Path</span>
          <span>${escapeHtml(this.roomLabel(path.fromRoomId))} to ${escapeHtml(this.roomLabel(path.toRoomId))}</span>
        </div>
        <div class="venue-selected-room-meta">
          <span>${path.points.length} waypoints</span>
          ${this.selectedPathPointIndex !== undefined ? `<span>Waypoint ${this.selectedPathPointIndex + 1} selected</span>` : ""}
        </div>
        <div class="venue-selected-room-actions">
          <button class="hud-button hud-button-secondary" type="button" data-action="delete-selected-waypoint" ${this.selectedPathPointIndex !== undefined ? "" : "disabled"}>Delete Waypoint</button>
          <button class="hud-button hud-button-secondary" type="button" data-action="delete-selected-path">Delete Path</button>
          <button class="hud-button hud-button-secondary" type="button" data-action="clear-selection">Clear</button>
        </div>
      </aside>
    `;
  }

  private boardStyle(): string {
    return [
      `aspect-ratio: ${this.draft?.dimensions.width ?? 1} / ${this.draft?.dimensions.height ?? 1};`,
      `transform: translate(${this.boardViewport.pan.x.toFixed(1)}px, ${this.boardViewport.pan.y.toFixed(1)}px) scale(${this.boardViewport.zoom.toFixed(3)});`,
      `--venue-spot-inverse-scale: ${(1 / this.boardViewport.zoom).toFixed(4)};`,
    ].join(" ");
  }

  private renderSpot(spot: VenueSpot): string {
    if (!this.draft) {
      return "";
    }

    const selected = this.selectedSpotIds.has(spot.id);
    const anchor = this.primarySelectedSpotId === spot.id;
    const roomMismatch = this.editorMode === "spot" && !this.spotBelongsToAssignedRoom(spot);
    const spotRole = spot.role ?? "speaker";
    const roleLabel = spotRoleLabel(spotRole);
    const roleMarker = spotRole === "audience"
      ? `<span class="venue-spot-role-mark" aria-hidden="true">A</span>`
      : "";
    const className = [
      "venue-spot",
      `is-${spotRole}`,
      roomMismatch ? "is-room-mismatch" : "",
      selected ? "is-selected" : "",
      anchor ? "is-anchor" : "",
    ].filter(Boolean).join(" ");
    return `
      <button
        class="${className}"
        type="button"
        data-spot-id="${escapeHtml(spot.id)}"
        data-spot-role="${escapeHtml(spotRole)}"
        data-position="${formatPosition(spot.position)}"
        style="left: ${spotPercentX(spot, this.draft).toFixed(3)}%; top: ${spotPercentY(spot, this.draft).toFixed(3)}%; --spot-radius: ${SPOT_RADIUS};"
        aria-label="${escapeHtml(`${spot.id} ${roleLabel}`)}"
        title="${escapeHtml(`${spot.id} (${roleLabel})`)}"
      >${roleMarker}</button>
    `;
  }

  private bindEvents(): void {
    this.app.querySelectorAll<HTMLButtonElement>("[data-action='create-room']").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.preventDefault();
        this.createRoom();
      });
    });
    this.app.querySelectorAll<HTMLButtonElement>("[data-action='set-editor-mode']").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.preventDefault();
        const mode = button.dataset.editorMode;
        this.setEditorMode(mode === "spot" || mode === "path" ? mode : "room");
      });
    });
    this.app.querySelectorAll<HTMLButtonElement>("[data-action='clear-selection']").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.preventDefault();
        this.clearSelection();
      });
    });
    this.app.querySelectorAll<HTMLButtonElement>("[data-action='exit-room-editor']").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.preventDefault();
        this.exitRoomEditor();
      });
    });
    this.app.querySelectorAll<HTMLButtonElement>("[data-action='connect-rooms']").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        this.handleConnectRooms(button.dataset.fromRoomId, button.dataset.toRoomId);
      });
    });
    this.app.querySelectorAll<HTMLInputElement>("[data-room-name-input]").forEach((input) => {
      input.addEventListener("change", () => {
        this.updateRoomName(input.dataset.roomNameRoomId, input.value);
      });
      input.addEventListener("keydown", (event) => {
        if (event.key !== "Enter") {
          return;
        }
        event.preventDefault();
        input.dispatchEvent(new Event("change", { bubbles: true }));
      });
    });
    this.app.querySelectorAll<HTMLButtonElement>("[data-action='add-room-spot']").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.preventDefault();
        this.addSpotToRoom(button.dataset.roomPanelRoomId);
      });
    });
    this.app.querySelectorAll<HTMLButtonElement>("[data-action='copy-selected-spots']").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.preventDefault();
        if (!button.disabled) {
          this.copySelectedRoomSpots();
        }
      });
    });
    this.app.querySelectorAll<HTMLButtonElement>("[data-action='paste-room-spots']").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.preventDefault();
        if (!button.disabled) {
          this.pasteSpotsIntoSelectedRoom();
        }
      });
    });
    this.app.querySelectorAll<HTMLButtonElement>("[data-action='delete-selected-spots']").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.preventDefault();
        if (!button.disabled) {
          this.deleteSelectedSpots();
        }
      });
    });
    this.app.querySelectorAll<HTMLButtonElement>("[data-action='delete-selected-path']").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.preventDefault();
        this.deleteSelectedPath();
      });
    });
    this.app.querySelectorAll<HTMLButtonElement>("[data-action='delete-selected-waypoint']").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.preventDefault();
        if (!button.disabled) {
          this.deleteSelectedPathPoint();
        }
      });
    });
    this.app.querySelectorAll<HTMLButtonElement>("[data-action='delete-connected-room-path']").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        this.deleteRoomPathById(button.dataset.roomPathId);
      });
    });
    this.app.querySelectorAll<HTMLElement>("[data-connected-room-path-id]").forEach((row) => {
      row.addEventListener("mouseenter", () => this.handleConnectedRoomMouseEnter(row.dataset.connectedRoomPathId));
      row.addEventListener("mouseleave", () => this.handleConnectedRoomMouseLeave(row.dataset.connectedRoomPathId));
    });
    const boardShell = this.app.querySelector<HTMLElement>("[data-board-shell]");
    boardShell?.addEventListener("wheel", (event) => {
      this.handleBoardWheel(event);
    }, { passive: false });
    boardShell?.addEventListener("pointerdown", (event) => {
      this.handleBoardPointerDown(event);
    });
    const board = this.app.querySelector<HTMLElement>("[data-board]");
    board?.addEventListener("click", (event) => {
      this.handleBoardClick(event);
    });
    board?.addEventListener("pointermove", (event) => {
      this.updateBoardPointerPosition(event);
    });
    board?.addEventListener("pointerdown", (event) => {
      this.updateBoardPointerPosition(event);
    });

    this.app.querySelectorAll<HTMLButtonElement>("[data-spot-id]").forEach((button) => {
      button.addEventListener("click", (event) => this.handleSpotClick(event, button.dataset.spotId));
      button.addEventListener("contextmenu", (event) => this.handleSpotContextMenu(event, button.dataset.spotId));
      button.addEventListener("dblclick", (event) => this.handleSpotDoubleClick(event, button.dataset.spotId));
      button.addEventListener("pointerdown", (event) => this.handleSpotPointerDown(event, button.dataset.spotId));
    });
    this.app.querySelectorAll<HTMLElement>(".venue-room-rect[data-room-id]").forEach((element) => {
      element.addEventListener("click", (event) => this.handleRoomClick(event, element.dataset.roomId));
      element.addEventListener("dblclick", (event) => this.handleRoomDoubleClick(event, element.dataset.roomId));
      element.addEventListener("pointerdown", (event) => this.handleRoomPointerDown(event, element.dataset.roomId));
      element.addEventListener("mouseenter", () => this.handleRoomMouseEnter(element.dataset.roomId));
      element.addEventListener("mouseleave", () => this.handleRoomMouseLeave(element.dataset.roomId));
    });
    this.app.querySelectorAll<HTMLElement>("[data-room-resize-room-id]").forEach((element) => {
      element.addEventListener("pointerdown", (event) => this.handleRoomResizePointerDown(event, element.dataset.roomResizeRoomId));
    });
    this.app.querySelectorAll<HTMLButtonElement>("[data-path-connect-room-id]").forEach((button) => {
      button.addEventListener("pointerdown", (event) => this.handlePathConnectPointerDown(event, button.dataset.pathConnectRoomId));
    });
    this.app.querySelectorAll<HTMLButtonElement>("[data-path-id][data-path-point-index]").forEach((button) => {
      button.addEventListener("pointerdown", (event) => this.handlePathPointPointerDown(event, button.dataset.pathId, button.dataset.pathPointIndex));
    });
    this.app.querySelectorAll<SVGPolylineElement>("[data-room-path]").forEach((path) => {
      path.addEventListener("click", (event) => this.handleRoomPathClick(event, path.dataset.roomPath));
    });
    this.app.querySelectorAll<SVGPolylineElement>("[data-room-path-hit]").forEach((path) => {
      path.addEventListener("click", (event) => this.handleRoomPathClick(event, path.dataset.roomPathHit));
    });
  }

  private clearSelection(): void {
    this.resetVenueSelection();
    this.render();
  }

  private resetVenueSelection(options: { clearActiveRoom?: boolean; clearSelectedRoom?: boolean } = {}): void {
    const clearSelectedRoom = options.clearSelectedRoom ?? true;
    if (options.clearActiveRoom) {
      this.activeRoomId = undefined;
    }
    this.selectedSpotIds = new Set();
    if (clearSelectedRoom) {
      this.selectedRoomId = undefined;
    }
    this.connectTargetRoomId = undefined;
    this.hoverRoomId = undefined;
    this.hoverPathId = undefined;
    this.selectedPathId = undefined;
    this.selectedPathPointIndex = undefined;
    this.pathEditing = false;
    this.connectDragState = undefined;
    this.primarySelectedSpotId = undefined;
  }

  private setEditorMode(mode: EditorMode): void {
    if (this.activeRoomId || this.editorMode === mode) {
      return;
    }

    this.editorMode = mode;
    this.resetVenueSelection();
    this.render();
  }

  private createRoom(center?: Position): void {
    if (!this.draft || this.activeRoomId || this.editorMode !== "room") {
      return;
    }

    const result = createRoom(this.draft, center ? { center } : undefined);
    this.draft = result.draft;
    this.resetVenueSelection();
    this.selectedRoomId = result.room.id;
    this.markDirty();
    this.render();
  }

  private handleBoardWheel(event: WheelEvent): void {
    if (!this.draft) {
      return;
    }

    const board = this.app.querySelector<HTMLElement>("[data-board]");
    if (!board) {
      return;
    }
    const rect = board.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) {
      return;
    }

    event.preventDefault();
    const previous = this.boardViewport;
    const nextZoom = clamp(previous.zoom * Math.exp(event.deltaY * WHEEL_ZOOM_SPEED), MIN_ZOOM, MAX_ZOOM);
    if (nextZoom === previous.zoom) {
      return;
    }

    const baseLeft = rect.left - previous.pan.x;
    const baseTop = rect.top - previous.pan.y;
    const localX = (event.clientX - rect.left) / previous.zoom;
    const localY = (event.clientY - rect.top) / previous.zoom;
    this.boardViewport = {
      zoom: nextZoom,
      pan: {
        x: event.clientX - baseLeft - localX * nextZoom,
        y: event.clientY - baseTop - localY * nextZoom,
      },
    };
    this.applyBoardViewport();
  }

  private handleBoardPointerDown(event: PointerEvent): void {
    if (this.pathEditing) {
      return;
    }

    if (event.button !== 0 || isBoardControlTarget(event.target)) {
      return;
    }

    const shell = this.app.querySelector<HTMLElement>("[data-board-shell]");
    if (!shell) {
      return;
    }

    event.preventDefault();
    this.mapPanState = {
      pointerId: event.pointerId,
      startClient: { x: event.clientX, y: event.clientY },
      startPan: { ...this.boardViewport.pan },
    };
    shell.classList.add("is-panning");
    shell.setPointerCapture(event.pointerId);

    const onPointerMove = (moveEvent: PointerEvent): void => this.handleBoardPointerMove(moveEvent);
    const onPointerUp = (upEvent: PointerEvent): void => {
      if (upEvent.pointerId !== this.mapPanState?.pointerId) {
        return;
      }

      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", onPointerUp);
      shell.classList.remove("is-panning");
      this.mapPanState = undefined;
    };

    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerUp);
  }

  private handleBoardClick(event: MouseEvent): void {
    if (
      !this.draft ||
      !this.canEditPathsInOverview() ||
      !this.pathEditing ||
      !this.selectedPathId ||
      isPathEditControlTarget(event.target)
    ) {
      return;
    }

    if (this.addPointToSelectedPath(event.clientX, event.clientY)) {
      event.preventDefault();
    }
  }

  private handleBoardPointerMove(event: PointerEvent): void {
    if (!this.mapPanState || event.pointerId !== this.mapPanState.pointerId) {
      return;
    }

    const delta = {
      x: event.clientX - this.mapPanState.startClient.x,
      y: event.clientY - this.mapPanState.startClient.y,
    };
    this.boardViewport = {
      ...this.boardViewport,
      pan: {
        x: this.mapPanState.startPan.x + delta.x,
        y: this.mapPanState.startPan.y + delta.y,
      },
    };
    this.applyBoardViewport();
  }

  private applyBoardViewport(): void {
    const board = this.app.querySelector<HTMLElement>("[data-board]");
    if (!board) {
      return;
    }

    board.style.transform = `translate(${this.boardViewport.pan.x.toFixed(1)}px, ${this.boardViewport.pan.y.toFixed(1)}px) scale(${this.boardViewport.zoom.toFixed(3)})`;
    board.style.setProperty("--venue-spot-inverse-scale", (1 / this.boardViewport.zoom).toFixed(4));
    board.dataset.panX = this.boardViewport.pan.x.toFixed(1);
    board.dataset.panY = this.boardViewport.pan.y.toFixed(1);
    board.dataset.zoom = this.boardViewport.zoom.toFixed(3);
  }

  private handleSpotClick(event: MouseEvent, spotId: string | undefined): void {
    if (!spotId || !this.draft || this.dragState || !this.canEditSpot(spotId)) {
      return;
    }

    if (this.suppressNextClick) {
      this.suppressNextClick = false;
      return;
    }

    if (event.shiftKey) {
      this.selectedSpotIds = toggleSelection(this.selectedSpotIds, spotId);
    } else {
      this.selectedSpotIds = new Set([spotId]);
    }
    this.selectedRoomId = this.currentSpotEditRoomId();
    this.primarySelectedSpotId = spotId;
    this.render();
  }

  private handleSpotContextMenu(event: MouseEvent, spotId: string | undefined): void {
    if (this.suppressNextClick && event.ctrlKey && !event.metaKey) {
      event.preventDefault();
    }
  }

  private handleSpotDoubleClick(event: MouseEvent, spotId: string | undefined): void {
    if (!spotId || !this.draft || this.dragState || !this.canEditSpot(spotId)) {
      return;
    }

    event.preventDefault();
    event.stopPropagation();
    this.toggleSpotRole(spotId);
  }

  private handleSpotPointerDown(event: PointerEvent, spotId: string | undefined): void {
    if (!spotId || !this.draft || event.button !== 0 || !this.canEditSpot(spotId)) {
      return;
    }

    if (event.metaKey || event.ctrlKey || event.shiftKey) {
      return;
    }

    if (!this.selectedSpotIds.has(spotId)) {
      this.selectedSpotIds = new Set([spotId]);
      this.selectedRoomId = this.currentSpotEditRoomId();
      this.primarySelectedSpotId = spotId;
    }

    const board = this.app.querySelector<HTMLElement>("[data-board]");
    if (!board) {
      return;
    }

    const origin = clientToBoard(event.clientX, event.clientY, board, this.draft);
    if (!origin) {
      return;
    }
    const selected = new Set(this.selectedSpotIds);
    const startPositions = new Map(
      this.draft.spots
        .filter((spot) => selected.has(spot.id))
        .map((spot) => [spot.id, { ...spot.position }] as const),
    );
    this.dragState = {
      pointerId: event.pointerId,
      origin,
      startPositions,
      moved: false,
    };
    (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);

    const onPointerMove = (moveEvent: PointerEvent): void => this.handlePointerMove(moveEvent);
    const onPointerUp = (upEvent: PointerEvent): void => {
      if (upEvent.pointerId !== this.dragState?.pointerId) {
        return;
      }

      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", onPointerUp);
      const moved = this.dragState.moved;
      this.dragState = undefined;
      if (moved) {
        this.suppressNextClick = true;
        this.markDirty();
        this.render();
      }
    };

    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerUp);
  }

  private handlePointerMove(event: PointerEvent): void {
    if (!this.draft || !this.dragState || event.pointerId !== this.dragState.pointerId) {
      return;
    }

    const board = this.app.querySelector<HTMLElement>("[data-board]");
    if (!board) {
      return;
    }
    const current = clientToBoard(event.clientX, event.clientY, board, this.draft);
    if (!current) {
      return;
    }
    const delta = {
      x: current.x - this.dragState.origin.x,
      y: current.y - this.dragState.origin.y,
    };
    if (Math.abs(delta.x) > 0.03 || Math.abs(delta.y) > 0.03) {
      this.dragState.moved = true;
    }
    const startPositions = this.dragState.startPositions;
    this.draft = {
      ...this.draft,
      spots: this.draft.spots.map((spot) => {
        const start = startPositions.get(spot.id);
        return start
          ? {
              ...spot,
              position: {
                x: clamp(roundTo(start.x + delta.x, 0.1), 0, this.draft!.dimensions.width - 1),
                y: clamp(roundTo(start.y + delta.y, 0.1), 0, this.draft!.dimensions.height - 1),
              },
            }
          : spot;
      }),
    };
    this.render();
  }

  private handleRoomPointerDown(event: PointerEvent, roomId: string | undefined): void {
    if (!roomId || !this.draft || this.editorMode !== "room" || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey) {
      return;
    }
    if (this.selectedRoomId !== roomId || this.connectTargetRoomId) {
      return;
    }

    const room = this.draft.rooms.find((candidate) => candidate.id === roomId);
    const board = this.app.querySelector<HTMLElement>("[data-board]");
    if (!room || !board) {
      return;
    }

    const origin = clientToBoard(event.clientX, event.clientY, board, this.draft);
    if (!origin) {
      return;
    }

    this.selectedSpotIds = new Set();
    this.connectTargetRoomId = undefined;
    this.selectedPathId = undefined;
    this.pathEditing = false;
    this.primarySelectedSpotId = undefined;
    this.roomDragState = {
      pointerId: event.pointerId,
      roomId,
      origin,
      startRect: this.roomRectFor(room),
      moved: false,
    };
    (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);

    const onPointerMove = (moveEvent: PointerEvent): void => this.handleRoomPointerMove(moveEvent);
    const onPointerUp = (upEvent: PointerEvent): void => {
      if (upEvent.pointerId !== this.roomDragState?.pointerId) {
        return;
      }

      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", onPointerUp);
      const moved = this.roomDragState.moved;
      this.roomDragState = undefined;
      if (moved) {
        this.suppressNextRoomClick = true;
        this.markDirty();
        this.render();
      }
    };

    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerUp);
  }

  private handleRoomPointerMove(event: PointerEvent): void {
    if (!this.draft || !this.roomDragState || event.pointerId !== this.roomDragState.pointerId) {
      return;
    }

    const board = this.app.querySelector<HTMLElement>("[data-board]");
    if (!board) {
      return;
    }

    const current = clientToBoard(event.clientX, event.clientY, board, this.draft);
    if (!current) {
      return;
    }

    const delta = {
      x: current.x - this.roomDragState.origin.x,
      y: current.y - this.roomDragState.origin.y,
    };
    if (Math.abs(delta.x) > 0.03 || Math.abs(delta.y) > 0.03) {
      this.roomDragState.moved = true;
    }
    const startRect = this.roomDragState.startRect;
    this.draft = moveRoomRect(this.draft, this.roomDragState.roomId, {
      x: clamp(roundTo(startRect.x + delta.x, 0.1), 0, this.draft.dimensions.width - startRect.width),
      y: clamp(roundTo(startRect.y + delta.y, 0.1), 0, this.draft.dimensions.height - startRect.height),
    });
    this.render();
  }

  private handleRoomResizePointerDown(event: PointerEvent, roomId: string | undefined): void {
    if (!roomId || !this.draft || this.editorMode !== "room" || event.button !== 0) {
      return;
    }

    const room = this.roomForId(roomId);
    const board = this.app.querySelector<HTMLElement>("[data-board]");
    if (!room || !board) {
      return;
    }

    const origin = clientToBoard(event.clientX, event.clientY, board, this.draft);
    if (!origin) {
      return;
    }

    event.preventDefault();
    event.stopPropagation();
    this.selectedRoomId = roomId;
    this.connectTargetRoomId = undefined;
    this.roomResizeState = {
      pointerId: event.pointerId,
      roomId,
      origin,
      startRect: this.roomRectFor(room),
      moved: false,
    };
    (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);

    const onPointerMove = (moveEvent: PointerEvent): void => this.handleRoomResizePointerMove(moveEvent);
    const onPointerUp = (upEvent: PointerEvent): void => {
      if (upEvent.pointerId !== this.roomResizeState?.pointerId) {
        return;
      }

      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", onPointerUp);
      const moved = this.roomResizeState.moved;
      this.roomResizeState = undefined;
      if (moved) {
        this.suppressNextRoomClick = true;
        this.markDirty();
      }
      this.render();
    };

    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerUp);
  }

  private handleRoomResizePointerMove(event: PointerEvent): void {
    if (!this.draft || !this.roomResizeState || event.pointerId !== this.roomResizeState.pointerId) {
      return;
    }

    const board = this.app.querySelector<HTMLElement>("[data-board]");
    if (!board) {
      return;
    }

    const current = clientToBoard(event.clientX, event.clientY, board, this.draft);
    if (!current) {
      return;
    }

    const delta = {
      x: current.x - this.roomResizeState.origin.x,
      y: current.y - this.roomResizeState.origin.y,
    };
    if (Math.abs(delta.x) > 0.03 || Math.abs(delta.y) > 0.03) {
      this.roomResizeState.moved = true;
    }
    const startRect = this.roomResizeState.startRect;
    this.draft = resizeRoomRect(this.draft, this.roomResizeState.roomId, {
      width: clamp(roundTo(startRect.width + delta.x, 0.1), 1, this.draft.dimensions.width - startRect.x),
      height: clamp(roundTo(startRect.height + delta.y, 0.1), 1, this.draft.dimensions.height - startRect.y),
    });
    this.render();
  }

  private handleKeyDown(event: KeyboardEvent): void {
    if (event.key === "Escape") {
      if (this.hasVenueEditorSelection()) {
        this.returnToRoomView();
        event.preventDefault();
      }
      return;
    }

    if ((event.key === "Backspace" || event.key === "Delete") && !event.defaultPrevented && !isTypingTarget(event.target)) {
      if (this.deleteSelectedPathPoint()) {
        event.preventDefault();
        return;
      }
      if (this.deleteSelectedPath()) {
        event.preventDefault();
        return;
      }
      this.deleteSelectedSpots();
      event.preventDefault();
      return;
    }

    const usesCommand = event.metaKey || event.ctrlKey;
    if (!usesCommand || event.defaultPrevented || isTypingTarget(event.target)) {
      return;
    }

    if (event.key.toLowerCase() === "l") {
      event.preventDefault();
      return;
    }

    if (event.key.toLowerCase() === "n") {
      this.createRoom(this.lastBoardPointerPosition);
      event.preventDefault();
      return;
    }

    if (event.key.toLowerCase() === "s") {
      if (this.toggleSelectedSpotRoles()) {
        event.preventDefault();
        return;
      }
      event.preventDefault();
      return;
    }

    if (event.key.toLowerCase() === "r") {
      event.preventDefault();
      return;
    }

    if (event.key.toLowerCase() === "x") {
      this.cutSelectedRoomSpots();
      event.preventDefault();
      return;
    }

    if (event.key.toLowerCase() === "c") {
      this.copySelectedRoomSpots();
      event.preventDefault();
      return;
    }

    if (event.key.toLowerCase() === "v") {
      this.pasteSpotsIntoSelectedRoom();
      event.preventDefault();
    }
  }

  private updateBoardPointerPosition(event: PointerEvent): void {
    if (!this.draft) {
      return;
    }

    const board = this.app.querySelector<HTMLElement>("[data-board]");
    if (!board) {
      return;
    }

    this.lastBoardPointerPosition = clientToBoard(event.clientX, event.clientY, board, this.draft);
  }

  private handleRoomClick(event: MouseEvent, roomId: string | undefined): void {
    if (!roomId || !this.draft || this.activeRoomId || this.editorMode !== "room") {
      return;
    }
    if (this.pathEditing) {
      return;
    }

    const room = this.draft.rooms.find((candidate) => candidate.id === roomId);
    if (!room) {
      return;
    }

    event.preventDefault();
    const previousClick = this.lastRoomClick;
    this.lastRoomClick = { roomId, timeStamp: event.timeStamp };
    if (event.detail >= 2 || (previousClick?.roomId === roomId && event.timeStamp - previousClick.timeStamp < 500)) {
      this.enterRoomEditor(roomId);
      return;
    }

    if (this.suppressNextRoomClick) {
      this.suppressNextRoomClick = false;
      return;
    }

    if (this.selectedRoomId && this.selectedRoomId !== roomId && !this.roomsConnected(this.selectedRoomId, roomId)) {
      this.selectedSpotIds = new Set();
      this.primarySelectedSpotId = undefined;
      this.connectTargetRoomId = roomId;
      this.hoverPathId = undefined;
      this.selectedPathId = undefined;
      this.pathEditing = false;
      this.render();
      return;
    }

    this.selectedSpotIds = new Set();
    this.primarySelectedSpotId = undefined;
    this.pathEditing = false;
    if (this.selectedRoomId === roomId && !this.connectTargetRoomId) {
      this.enterRoomEditor(roomId);
      return;
    }

    this.selectedRoomId = roomId;
    this.connectTargetRoomId = undefined;
    this.hoverPathId = undefined;
    this.selectedPathId = undefined;
    this.render();
  }

  private handleRoomMouseEnter(roomId: string | undefined): void {
    if (!roomId || !this.draft || this.activeRoomId || this.editorMode !== "room") {
      return;
    }

    this.hoverRoomId = roomId;
    this.setHoverPath(this.pathBetweenSelectedRoomAnd(roomId));
  }

  private handleRoomMouseLeave(roomId: string | undefined): void {
    if (!roomId || this.hoverRoomId !== roomId) {
      return;
    }

    this.hoverRoomId = undefined;
    this.setHoverPath(undefined);
  }

  private handleConnectedRoomMouseEnter(pathId: string | undefined): void {
    this.setHoverPath(pathId);
  }

  private handleConnectedRoomMouseLeave(pathId: string | undefined): void {
    if (pathId && this.hoverPathId !== pathId) {
      return;
    }

    this.setHoverPath(undefined);
  }

  private handleRoomDoubleClick(event: MouseEvent, roomId: string | undefined): void {
    if (!roomId || !this.draft || this.editorMode !== "room") {
      return;
    }

    event.preventDefault();
    event.stopPropagation();
    this.enterRoomEditor(roomId);
  }

  private enterRoomEditor(roomId: string): void {
    const room = this.roomForId(roomId);
    if (!room) {
      return;
    }

    this.activeRoomId = roomId;
    this.selectedRoomId = roomId;
    this.connectTargetRoomId = undefined;
    this.hoverPathId = undefined;
    this.selectedPathId = undefined;
    this.pathEditing = false;
    this.selectedSpotIds = new Set();
    this.primarySelectedSpotId = undefined;
    this.saveStatus = `Editing ${room.label}`;
    this.render();
  }

  private handlePathConnectPointerDown(event: PointerEvent, roomId: string | undefined): void {
    if (!roomId || !this.draft || this.activeRoomId || this.editorMode !== "path" || event.button !== 0) {
      return;
    }

    const room = this.roomForId(roomId);
    const board = this.app.querySelector<HTMLElement>("[data-board]");
    if (!room || !board) {
      return;
    }

    event.preventDefault();
    event.stopPropagation();
    const fromPosition = rectCenter(this.roomRectFor(room));
    this.selectedRoomId = roomId;
    this.connectTargetRoomId = undefined;
    this.selectedPathId = undefined;
    this.selectedPathPointIndex = undefined;
    this.pathEditing = false;
    this.hoverRoomId = undefined;
    this.hoverPathId = undefined;
    this.connectDragState = {
      pointerId: event.pointerId,
      fromRoomId: roomId,
      fromPosition,
      currentPosition: fromPosition,
    };
    this.saveStatus = `Drag from ${room.label} to another room to create a path`;
    this.render();

    const onPointerMove = (moveEvent: PointerEvent): void => this.handlePathConnectPointerMove(moveEvent);
    const onPointerUp = (upEvent: PointerEvent): void => {
      if (upEvent.pointerId !== this.connectDragState?.pointerId) {
        return;
      }

      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", onPointerUp);
      this.finishPathConnectDrag(upEvent.clientX, upEvent.clientY);
    };

    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerUp);
  }

  private handlePathConnectPointerMove(event: PointerEvent): void {
    if (!this.draft || !this.connectDragState || event.pointerId !== this.connectDragState.pointerId) {
      return;
    }

    const board = this.app.querySelector<HTMLElement>("[data-board]");
    if (!board) {
      return;
    }

    const current = clientToBoard(event.clientX, event.clientY, board, this.draft);
    if (!current) {
      return;
    }

    const targetRoomId = this.roomIdAtClientPosition(event.clientX, event.clientY, this.connectDragState.fromRoomId);
    this.connectDragState = {
      ...this.connectDragState,
      currentPosition: {
        x: clamp(roundTo(current.x, 0.1), 0, this.draft.dimensions.width - 1),
        y: clamp(roundTo(current.y, 0.1), 0, this.draft.dimensions.height - 1),
      },
    };
    this.connectTargetRoomId = targetRoomId;
    this.render();
  }

  private finishPathConnectDrag(clientX: number, clientY: number): void {
    if (!this.connectDragState) {
      return;
    }

    const fromRoomId = this.connectDragState.fromRoomId;
    const targetRoomId = this.roomIdAtClientPosition(clientX, clientY, fromRoomId);
    this.connectDragState = undefined;
    if (!targetRoomId) {
      this.connectTargetRoomId = undefined;
      this.saveStatus = "Path creation cancelled";
      this.render();
      return;
    }

    this.handleConnectRooms(fromRoomId, targetRoomId);
  }

  private handleRoomPathClick(event: MouseEvent, pathId: string | undefined): void {
    if (!this.draft || !pathId || this.activeRoomId || !this.canEditPathsInOverview()) {
      return;
    }

    const path = this.draft.paths.find((candidate) => candidate.id === pathId);
    if (!path) {
      return;
    }

    event.preventDefault();
    event.stopPropagation();
    if (this.pathEditing && this.selectedPathId === pathId) {
      this.addPointToSelectedPath(event.clientX, event.clientY);
      return;
    }

    this.selectedRoomId = undefined;
    this.connectTargetRoomId = undefined;
    this.hoverRoomId = undefined;
    this.hoverPathId = undefined;
    this.selectedSpotIds = new Set();
    this.primarySelectedSpotId = undefined;
    this.selectedPathId = pathId;
    this.selectedPathPointIndex = undefined;
    this.pathEditing = true;
    this.saveStatus = `Editing path ${this.roomLabel(path.fromRoomId)} to ${this.roomLabel(path.toRoomId)}`;
    this.render();
  }

  private addPointToSelectedPath(clientX: number, clientY: number): boolean {
    if (!this.draft || !this.selectedPathId || !this.pathEditing) {
      return false;
    }

    const board = this.app.querySelector<HTMLElement>("[data-board]");
    if (!board) {
      return false;
    }

    const position = clientToBoard(clientX, clientY, board, this.draft);
    if (!position) {
      return false;
    }

    this.draft = addRoomPathPoint(this.draft, this.selectedPathId, {
      x: clamp(roundTo(position.x, 0.1), 0, this.draft.dimensions.width - 1),
      y: clamp(roundTo(position.y, 0.1), 0, this.draft.dimensions.height - 1),
    });
    const path = this.draft.paths.find((candidate) => candidate.id === this.selectedPathId);
    this.selectedPathPointIndex = path ? path.points.length - 1 : undefined;
    this.markDirty();
    this.render();
    return true;
  }

  private roomIdAtClientPosition(clientX: number, clientY: number, ignoreRoomId?: string): string | undefined {
    const target = document.elementFromPoint(clientX, clientY);
    const roomElement = target instanceof Element ? target.closest<HTMLElement>("[data-room-id]") : undefined;
    const roomId = roomElement?.dataset.roomId;
    if (!roomId || roomId === ignoreRoomId) {
      return undefined;
    }
    return roomId;
  }

  private handleConnectRooms(fromRoomId: string | undefined, toRoomId: string | undefined): void {
    if (!this.draft || !fromRoomId || !toRoomId) {
      return;
    }

    const pathId = normalizeRoomPathId(fromRoomId, toRoomId);
    const existing = this.draft.paths.find((path) => path.id === pathId);
    this.draft = upsertRoomPath(this.draft, fromRoomId, toRoomId, existing?.points ?? []);
    this.selectedRoomId = undefined;
    this.connectTargetRoomId = undefined;
    this.connectDragState = undefined;
    this.hoverRoomId = undefined;
    this.hoverPathId = undefined;
    this.selectedPathId = pathId;
    this.selectedPathPointIndex = undefined;
    this.pathEditing = true;
    if (!existing) {
      this.markDirty();
    }
    this.saveStatus = `${existing ? "Editing" : "Connected"} ${this.roomLabel(fromRoomId)} to ${this.roomLabel(toRoomId)}`;
    this.render();
  }

  private handlePathPointPointerDown(event: PointerEvent, pathId: string | undefined, pointIndexValue: string | undefined): void {
    if (!this.draft || !pathId || pointIndexValue === undefined || event.button !== 0) {
      return;
    }

    const pointIndex = Number.parseInt(pointIndexValue, 10);
    const path = this.draft.paths.find((candidate) => candidate.id === pathId);
    const point = path?.points[pointIndex];
    const board = this.app.querySelector<HTMLElement>("[data-board]");
    if (!path || !point || !board) {
      return;
    }

    const origin = clientToBoard(event.clientX, event.clientY, board, this.draft);
    if (!origin) {
      return;
    }

    event.preventDefault();
    event.stopPropagation();
    this.selectedPathPointIndex = pointIndex;
    this.pathPointDragState = {
      pointerId: event.pointerId,
      pathId,
      pointIndex,
      origin,
      startPosition: { ...point },
      moved: false,
    };
    (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);

    const onPointerMove = (moveEvent: PointerEvent): void => this.handlePathPointPointerMove(moveEvent);
    const onPointerUp = (upEvent: PointerEvent): void => {
      if (upEvent.pointerId !== this.pathPointDragState?.pointerId) {
        return;
      }

      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", onPointerUp);
      const moved = this.pathPointDragState.moved;
      this.pathPointDragState = undefined;
      if (moved) {
        this.markDirty();
      }
      this.render();
    };

    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerUp);
  }

  private handlePathPointPointerMove(event: PointerEvent): void {
    if (!this.draft || !this.pathPointDragState || event.pointerId !== this.pathPointDragState.pointerId) {
      return;
    }

    const board = this.app.querySelector<HTMLElement>("[data-board]");
    if (!board) {
      return;
    }

    const current = clientToBoard(event.clientX, event.clientY, board, this.draft);
    if (!current) {
      return;
    }

    const delta = {
      x: current.x - this.pathPointDragState.origin.x,
      y: current.y - this.pathPointDragState.origin.y,
    };
    if (Math.abs(delta.x) > 0.03 || Math.abs(delta.y) > 0.03) {
      this.pathPointDragState.moved = true;
    }
    this.draft = moveRoomPathPoint(this.draft, this.pathPointDragState.pathId, this.pathPointDragState.pointIndex, {
      x: clamp(roundTo(this.pathPointDragState.startPosition.x + delta.x, 0.1), 0, this.draft.dimensions.width - 1),
      y: clamp(roundTo(this.pathPointDragState.startPosition.y + delta.y, 0.1), 0, this.draft.dimensions.height - 1),
    });
    this.render();
  }

  private async save(): Promise<void> {
    if (!this.draft) {
      return;
    }

    const revision = this.dirtyRevision;
    const draftToSave = this.draft;
    this.saveStatus = "Saving";
    this.render();
    try {
      const response = await fetch("/api/venue-editor", {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(draftToSave),
      });
      if (!response.ok) {
        throw new Error(`${response.status} ${response.statusText}`);
      }

      const body = await response.json() as VenueEditorStateResponse;
      if (this.dirtyRevision === revision) {
        this.draft = stripUpdatedAt(body.state);
        this.saveStatus = "Saved";
        this.dirty = false;
      } else {
        this.scheduleAutosave();
      }
    } catch (error) {
      if (this.dirtyRevision === revision) {
        this.saveStatus = `Autosave failed: ${compactError(error)}`;
      } else {
        this.scheduleAutosave();
      }
    }
    this.render();
  }

  private visibleSpots(): VenueSpot[] {
    if (!this.draft) {
      return [];
    }

    if (!this.activeRoomId && this.editorMode === "spot") {
      return this.draft.spots;
    }

    if (!this.activeRoomId && this.editorMode === "room" && this.selectedRoomId) {
      return this.roomSpots(this.selectedRoomId);
    }

    if (!this.activeRoomId) {
      return [];
    }

    return this.draft.spots.filter((spot) => spot.roomId === this.activeRoomId);
  }

  private canEditPathsInOverview(): boolean {
    return this.editorMode === "room" || this.editorMode === "path";
  }

  private roomForId(roomId: string): VenueRoom | undefined {
    return this.draft?.rooms.find((room) => room.id === roomId);
  }

  private roomsConnected(firstRoomId: string, secondRoomId: string): boolean {
    const pathId = normalizeRoomPathId(firstRoomId, secondRoomId);
    return Boolean(this.draft?.paths.some((path) => path.id === pathId));
  }

  private pathBetweenSelectedRoomAnd(roomId: string): string | undefined {
    if (!this.selectedRoomId || this.selectedRoomId === roomId) {
      return undefined;
    }

    const pathId = normalizeRoomPathId(this.selectedRoomId, roomId);
    return this.draft?.paths.some((path) => path.id === pathId) ? pathId : undefined;
  }

  private setHoverPath(pathId: string | undefined): void {
    if (this.hoverPathId === pathId) {
      return;
    }

    this.hoverPathId = pathId;
    this.app.querySelectorAll<SVGPolylineElement>("[data-room-path]").forEach((path) => {
      path.classList.toggle("is-hovered", path.dataset.roomPath === pathId);
    });
    this.app.querySelectorAll<HTMLElement>("[data-connected-room-path-id]").forEach((row) => {
      row.classList.toggle("is-path-hovered", row.dataset.connectedRoomPathId === pathId);
    });
  }

  private connectedRoomsForRoom(roomId: string): Array<{ room: VenueRoom; path: VenueRoomPath }> {
    if (!this.draft) {
      return [];
    }

    return this.draft.paths
      .flatMap((path) => {
        const connectedRoomId = path.fromRoomId === roomId
          ? path.toRoomId
          : path.toRoomId === roomId
            ? path.fromRoomId
            : undefined;
        const room = connectedRoomId ? this.roomForId(connectedRoomId) : undefined;
        return room ? [{ room, path }] : [];
      })
      .sort((first, second) => first.room.label.localeCompare(second.room.label));
  }

  private isRoomConnectedPath(path: VenueRoomPath): boolean {
    return Boolean(
      this.selectedRoomId &&
      !this.pathEditing &&
      (path.fromRoomId === this.selectedRoomId || path.toRoomId === this.selectedRoomId),
    );
  }

  private roomSpots(roomId: string): VenueSpot[] {
    return this.draft?.spots.filter((spot) => spot.roomId === roomId) ?? [];
  }

  private roomRectFor(room: VenueRoom): VenueRect {
    return this.draft ? roomRect(room, this.draft) : room.rect ?? { x: 0, y: 0, width: 4, height: 3 };
  }

  private roomPathPoints(path: VenueRoomPath): Position[] {
    const fromRoom = this.roomForId(path.fromRoomId);
    const toRoom = this.roomForId(path.toRoomId);
    if (!fromRoom || !toRoom) {
      return [];
    }

    return [
      rectCenter(this.roomRectFor(fromRoom)),
      ...path.points.map((point) => ({ ...point })),
      rectCenter(this.roomRectFor(toRoom)),
    ];
  }

  private isSpotInActiveRoom(spotId: string): boolean {
    return Boolean(this.activeRoomId && this.spotForId(spotId)?.roomId === this.activeRoomId);
  }

  private canEditSpot(spotId: string): boolean {
    if (this.activeRoomId) {
      return this.isSpotInActiveRoom(spotId);
    }

    if (this.editorMode === "room" && this.selectedRoomId) {
      return this.spotForId(spotId)?.roomId === this.selectedRoomId;
    }

    return this.editorMode === "spot" && Boolean(this.spotForId(spotId));
  }

  private currentSpotEditRoomId(): string | undefined {
    if (this.activeRoomId) {
      return this.activeRoomId;
    }

    return this.editorMode === "room" ? this.selectedRoomId : undefined;
  }

  private selectedSpotIdsInRoom(roomId: string): Set<string> {
    return new Set(
      [...this.selectedSpotIds].filter((spotId) => this.spotForId(spotId)?.roomId === roomId),
    );
  }

  private selectedEditableSpotIds(): Set<string> {
    return new Set([...this.selectedSpotIds].filter((spotId) => this.canEditSpot(spotId)));
  }

  private exitRoomEditor(): void {
    this.activeRoomId = undefined;
    this.resetVenueSelection({ clearSelectedRoom: false });
    this.saveStatus = this.saveStatus.startsWith("Editing ")
      ? this.dirty ? "Autosaving" : "Ready"
      : this.saveStatus;
    this.render();
  }

  private hasVenueEditorSelection(): boolean {
    return Boolean(
      this.activeRoomId ||
      this.selectedRoomId ||
      this.selectedSpotIds.size > 0 ||
      this.connectTargetRoomId ||
      this.hoverRoomId ||
      this.selectedPathId ||
      this.selectedPathPointIndex !== undefined ||
      this.pathEditing,
    );
  }

  private returnToRoomView(): void {
    this.resetVenueSelection({ clearActiveRoom: true });
    this.saveStatus = this.saveStatus.startsWith("Editing ")
      ? this.dirty ? "Autosaving" : "Ready"
      : this.saveStatus;
    this.render();
  }

  private roomLabel(roomId: string): string {
    return this.roomForId(roomId)?.label ?? roomId;
  }

  private spotForId(spotId: string): VenueSpot | undefined {
    return this.draft?.spots.find((spot) => spot.id === spotId);
  }

  private isSpotAssignedToKnownRoom(spot: VenueSpot): boolean {
    return Boolean(spot.roomId && this.draft?.rooms.some((room) => room.id === spot.roomId));
  }

  private spotBelongsToAssignedRoom(spot: VenueSpot): boolean {
    const room = this.roomForId(spot.roomId);
    if (!room) {
      return false;
    }

    const rect = this.roomRectFor(room);
    return (
      spot.position.x >= rect.x &&
      spot.position.x <= rect.x + rect.width &&
      spot.position.y >= rect.y &&
      spot.position.y <= rect.y + rect.height
    );
  }

  private toggleSpotAssignmentForSelectedRoom(spotId: string): boolean {
    if (!this.draft || !this.selectedRoomId) {
      return false;
    }

    const spot = this.spotForId(spotId);
    const room = this.draft.rooms.find((candidate) => candidate.id === this.selectedRoomId);
    if (!spot || !room) {
      return false;
    }

    const wasAssigned = spot.roomId === this.selectedRoomId;
    this.draft = toggleSpotRoomAssignment(this.draft, spotId, this.selectedRoomId);
    this.selectedSpotIds = new Set();
    this.primarySelectedSpotId = undefined;
    this.markDirty();
    this.saveStatus = `${wasAssigned ? "Unassigned" : "Assigned"} ${spot.label} ${wasAssigned ? "from" : "to"} ${room.label}`;
    this.render();
    return true;
  }

  private updateRoomName(roomId: string | undefined, rawLabel: string): void {
    const label = rawLabel.trim();
    if (!this.draft || !roomId || label.length === 0) {
      this.render();
      return;
    }

    const room = this.roomForId(roomId);
    if (!room || room.label === label) {
      return;
    }

    this.draft = {
      ...this.draft,
      rooms: this.draft.rooms.map((candidate) =>
        candidate.id === roomId ? { ...candidate, label } : candidate,
      ),
    };
    this.markDirty();
    this.render();
  }

  private addSpotToRoom(roomId: string | undefined): void {
    if (!this.draft || !roomId) {
      return;
    }

    const room = this.roomForId(roomId);
    if (!room) {
      return;
    }

    const rect = this.roomRectFor(room);
    const spotId = nextRoomSpotId(roomId, this.draft.spots);
    const spot: VenueSpot = {
      id: spotId,
      roomId,
      label: spotId,
      position: {
        x: clamp(roundTo(rect.x + rect.width / 2, 0.1), 0, this.draft.dimensions.width - 1),
        y: clamp(roundTo(rect.y + rect.height / 2, 0.1), 0, this.draft.dimensions.height - 1),
      },
    };

    this.draft = {
      ...this.draft,
      rooms: this.draft.rooms.map((candidate) =>
        candidate.id === roomId
          ? { ...candidate, spotIds: [...candidate.spotIds, spot.id] }
          : candidate,
      ),
      spots: [...this.draft.spots, spot],
    };
    this.selectedSpotIds = new Set([spot.id]);
    this.selectedRoomId = roomId;
    this.primarySelectedSpotId = spot.id;
    this.markDirty();
    this.render();
  }

  private toggleSelectedSpotRoles(): boolean {
    if (!this.draft) {
      return false;
    }

    const selectedSpotIds = this.selectedEditableSpotIds();
    if (selectedSpotIds.size === 0) {
      return false;
    }

    this.draft = toggleSelectedSpotRoles(this.draft, selectedSpotIds);
    this.selectedSpotIds = selectedSpotIds;
    const audienceCount = [...selectedSpotIds].filter((spotId) => this.spotForId(spotId)?.role === "audience").length;
    this.markDirty();
    this.saveStatus = `${selectedSpotIds.size} spot${selectedSpotIds.size === 1 ? "" : "s"} set to ${audienceCount === selectedSpotIds.size ? "Audience" : "Participant"}`;
    this.render();
    return true;
  }

  private toggleSpotRole(spotId: string): boolean {
    if (!this.draft || !this.canEditSpot(spotId)) {
      return false;
    }

    const spot = this.spotForId(spotId);
    if (!spot) {
      return false;
    }

    this.draft = toggleSelectedSpotRoles(this.draft, new Set([spotId]));
    const nextRole = this.spotForId(spotId)?.role ?? "speaker";
    this.selectedSpotIds = new Set([spotId]);
    this.selectedRoomId = this.currentSpotEditRoomId();
    this.primarySelectedSpotId = spotId;
    this.markDirty();
    this.saveStatus = `${spot.label} set to ${spotRoleLabel(nextRole)}`;
    this.render();
    return true;
  }

  private copySelectedRoomSpots(): void {
    if (!this.draft) {
      return;
    }

    const roomId = this.currentSpotEditRoomId();
    if (!roomId) {
      return;
    }

    const selectedSpotIds = this.selectedSpotIdsInRoom(roomId);
    if (selectedSpotIds.size === 0) {
      return;
    }

    this.clipboard = copySelectedSpots(this.draft, selectedSpotIds);
    this.selectedRoomId = roomId;
    this.saveStatus = `${this.clipboard.spots.length} copied`;
    this.render();
  }

  private cutSelectedRoomSpots(): void {
    if (!this.draft) {
      return;
    }

    const roomId = this.currentSpotEditRoomId();
    if (!roomId) {
      return;
    }

    const selectedSpotIds = this.selectedSpotIdsInRoom(roomId);
    if (selectedSpotIds.size === 0) {
      return;
    }

    this.clipboard = copySelectedSpots(this.draft, selectedSpotIds);
    this.draft = {
      ...this.draft,
      rooms: this.draft.rooms.map((room) => ({
        ...room,
        spotIds: room.spotIds.filter((spotId) => !selectedSpotIds.has(spotId)),
      })),
      spots: this.draft.spots.filter((spot) => !selectedSpotIds.has(spot.id)),
      links: [],
    };
    this.selectedSpotIds = new Set();
    this.primarySelectedSpotId = undefined;
    this.markDirty();
    this.saveStatus = `${this.clipboard.spots.length} cut`;
    this.render();
  }

  private pasteSpotsIntoSelectedRoom(): void {
    if (!this.draft || !this.clipboard?.spots.length) {
      return;
    }

    const roomId = this.currentSpotEditRoomId();
    if (!roomId) {
      return;
    }

    const result = pasteCopiedSpotsIntoRoom(this.draft, this.clipboard, roomId, PASTE_OFFSET);
    if (result.selectedSpotIds.size === 0) {
      return;
    }

    this.draft = result.draft;
    this.selectedSpotIds = result.selectedSpotIds;
    this.selectedRoomId = roomId;
    this.primarySelectedSpotId = [...result.selectedSpotIds][0];
    this.markDirty();
    this.render();
  }

  private deleteSelectedSpots(): void {
    if (!this.draft) {
      return;
    }

    const roomId = this.currentSpotEditRoomId();
    if (!roomId) {
      return;
    }

    const selectedSpotIds = this.selectedSpotIdsInRoom(roomId);
    if (selectedSpotIds.size === 0) {
      return;
    }

    this.draft = {
      ...this.draft,
      rooms: this.draft.rooms.map((room) => ({
        ...room,
        spotIds: room.spotIds.filter((spotId) => !selectedSpotIds.has(spotId)),
      })),
      spots: this.draft.spots.filter((spot) => !selectedSpotIds.has(spot.id)),
      links: [],
    };
    this.selectedSpotIds = new Set();
    this.primarySelectedSpotId = undefined;
    this.markDirty();
    this.render();
  }

  private deleteSelectedPath(): boolean {
    if (!this.draft || !this.selectedPathId || !this.pathEditing) {
      return false;
    }

    const selectedPathId = this.selectedPathId;
    const selectedPath = this.draft.paths.find((path) => path.id === selectedPathId);
    if (!selectedPath) {
      this.selectedPathId = undefined;
      this.selectedPathPointIndex = undefined;
      this.pathEditing = false;
      this.connectTargetRoomId = undefined;
      this.render();
      return false;
    }

    return this.deleteRoomPathById(selectedPathId);
  }

  private deleteSelectedPathPoint(): boolean {
    if (!this.draft || !this.selectedPathId || this.selectedPathPointIndex === undefined || !this.pathEditing) {
      return false;
    }

    const selectedPath = this.draft.paths.find((path) => path.id === this.selectedPathId);
    if (!selectedPath || this.selectedPathPointIndex < 0 || this.selectedPathPointIndex >= selectedPath.points.length) {
      this.selectedPathPointIndex = undefined;
      this.render();
      return false;
    }

    const deletedIndex = this.selectedPathPointIndex;
    this.draft = deleteRoomPathPoint(this.draft, this.selectedPathId, deletedIndex);
    const nextPath = this.draft.paths.find((path) => path.id === this.selectedPathId);
    this.selectedPathPointIndex =
      nextPath && nextPath.points.length > 0
        ? Math.min(deletedIndex, nextPath.points.length - 1)
        : undefined;
    this.saveStatus = `Removed waypoint ${deletedIndex + 1}`;
    this.markDirty();
    this.render();
    return true;
  }

  private deleteRoomPathById(pathId: string | undefined): boolean {
    if (!this.draft || !pathId) {
      return false;
    }

    const selectedPath = this.draft.paths.find((path) => path.id === pathId);
    if (!selectedPath) {
      return false;
    }

    this.draft = deleteRoomPath(this.draft, selectedPath.id);
    if (this.hoverPathId === selectedPath.id) {
      this.hoverPathId = undefined;
    }
    if (this.selectedPathId === selectedPath.id) {
      this.selectedPathId = undefined;
      this.selectedPathPointIndex = undefined;
      this.pathEditing = false;
    }
    this.connectTargetRoomId = undefined;
    this.hoverRoomId = undefined;
    this.saveStatus = `Deleted path ${this.roomLabel(selectedPath.fromRoomId)} to ${this.roomLabel(selectedPath.toRoomId)}`;
    this.markDirty();
    this.render();
    return true;
  }

  private captureFocusedControl(): FocusSnapshot | undefined {
    const active = document.activeElement;
    if (!(active instanceof HTMLInputElement) || !active.hasAttribute("data-room-name-input")) {
      return undefined;
    }

    const roomId = active.dataset.roomNameRoomId;
    if (!roomId) {
      return undefined;
    }

    return {
      kind: "room-name",
      roomId,
      value: active.value,
      selectionStart: active.selectionStart,
      selectionEnd: active.selectionEnd,
    };
  }

  private restoreFocusedControl(snapshot: FocusSnapshot | undefined): void {
    if (!snapshot) {
      return;
    }

    const input = [...this.app.querySelectorAll<HTMLInputElement>("[data-room-name-input]")]
      .find((candidate) => candidate.dataset.roomNameRoomId === snapshot.roomId);
    if (!input) {
      return;
    }

    input.value = snapshot.value;
    input.focus({ preventScroll: true });
    if (snapshot.selectionStart !== null && snapshot.selectionEnd !== null) {
      input.setSelectionRange(snapshot.selectionStart, snapshot.selectionEnd);
    }
  }

  private markDirty(): void {
    this.dirty = true;
    this.dirtyRevision += 1;
    this.saveStatus = "Autosaving";
    this.scheduleAutosave();
  }

  private scheduleAutosave(): void {
    if (this.autosaveTimer !== undefined) {
      window.clearTimeout(this.autosaveTimer);
    }

    this.autosaveTimer = window.setTimeout(() => {
      this.autosaveTimer = undefined;
      void this.save();
    }, AUTOSAVE_DELAY_MS);
  }
}

function stripUpdatedAt(state: VenueEditorState): VenueEditorDraft {
  return {
    imageUrl: state.imageUrl,
    dimensions: state.dimensions,
    rooms: state.rooms,
    spots: state.spots,
    links: [],
    paths: state.paths,
  };
}

function toggleSelection(selectedSpotIds: ReadonlySet<string>, spotId: string): Set<string> {
  const next = new Set(selectedSpotIds);
  if (next.has(spotId)) {
    next.delete(spotId);
  } else {
    next.add(spotId);
  }
  return next;
}

function spotRoleLabel(role: NonNullable<VenueSpot["role"]>): string {
  return role === "audience" ? "Audience" : "Participant";
}

function spotPercentX(spot: VenueSpot, draft: VenueEditorDraft): number {
  return pointPercentX(spot.position, draft);
}

function spotPercentY(spot: VenueSpot, draft: VenueEditorDraft): number {
  return pointPercentY(spot.position, draft);
}

function pointPercentX(position: Position, draft: VenueEditorDraft): number {
  return ((position.x + 0.5) / draft.dimensions.width) * 100;
}

function pointPercentY(position: Position, draft: VenueEditorDraft): number {
  return ((position.y + 0.5) / draft.dimensions.height) * 100;
}

function rectPercentX(rect: VenueRect, draft: VenueEditorDraft): number {
  return (rect.x / draft.dimensions.width) * 100;
}

function rectPercentY(rect: VenueRect, draft: VenueEditorDraft): number {
  return (rect.y / draft.dimensions.height) * 100;
}

function rectPercentWidth(rect: VenueRect, draft: VenueEditorDraft): number {
  return (rect.width / draft.dimensions.width) * 100;
}

function rectPercentHeight(rect: VenueRect, draft: VenueEditorDraft): number {
  return (rect.height / draft.dimensions.height) * 100;
}

function rectCenter(rect: VenueRect): Position {
  return {
    x: rect.x + rect.width / 2,
    y: rect.y + rect.height / 2,
  };
}

function formatRect(rect: VenueRect): string {
  return `${formatNumber(rect.x)},${formatNumber(rect.y)},${formatNumber(rect.width)},${formatNumber(rect.height)}`;
}

function normalizeRoomPathId(firstRoomId: string, secondRoomId: string): string {
  return [firstRoomId, secondRoomId].sort().join("__");
}

function clientToBoard(clientX: number, clientY: number, board: HTMLElement, draft: VenueEditorDraft): Position | undefined {
  const rect = board.getBoundingClientRect();
  if (rect.width <= 0 || rect.height <= 0) {
    return undefined;
  }
  return {
    x: ((clientX - rect.left) / rect.width) * draft.dimensions.width - 0.5,
    y: ((clientY - rect.top) / rect.height) * draft.dimensions.height - 0.5,
  };
}

function nextRoomSpotId(roomId: string, spots: VenueSpot[]): string {
  const roomSlug = roomId
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "") || "room";
  const existingSpotIds = new Set(spots.map((spot) => spot.id));
  let index = 1;
  let candidate = `${roomSlug}_spot_${index}`;
  while (existingSpotIds.has(candidate)) {
    index += 1;
    candidate = `${roomSlug}_spot_${index}`;
  }
  return candidate;
}

function formatPosition(position: Position): string {
  return `${formatNumber(position.x)},${formatNumber(position.y)}`;
}

function formatNumber(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

function formatSavedAt(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "previously" : date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function roundTo(value: number, step: number): number {
  return Math.round(value / step) * step;
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(Math.max(value, minimum), maximum);
}

function isTypingTarget(target: EventTarget | null): boolean {
  return target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement;
}

function isBoardControlTarget(target: EventTarget | null): boolean {
  return target instanceof Element && Boolean(target.closest("button, [data-spot-id], [data-room-id], [data-room-resize-room-id], [data-room-path], [data-room-path-hit]"));
}

function isPathEditControlTarget(target: EventTarget | null): boolean {
  return target instanceof Element && Boolean(target.closest("[data-path-point-index], [data-action='connect-rooms'], [data-room-path], [data-room-path-hit], [data-room-id], [data-spot-id]"));
}

function compactError(error: unknown): string {
  return error instanceof Error ? error.message : "Unknown error";
}
