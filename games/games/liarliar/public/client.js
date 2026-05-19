let latestSocket = null;
const uiState = {
  bombKey: '',
  chatsKey: '',
  intelKey: '',
  manualOpen: new Set(),
  chatDrafts: new Map(),
};

const path = location.pathname;
if (path.includes('/clients/player')) playerClient();
else if (path.includes('/clients/global')) globalClient('/global');
else if (path.includes('/clients/admin')) adminClient();
else if (path.includes('/clients/replay')) replayClient();

function playerClient() {
  const ws = openSocket('/player' + location.search);
  ws.onmessage = (event) => {
    const message = JSON.parse(event.data);
    if (message.type === 'view') renderPlayer(message.view, ws);
    if (message.type === 'final') renderFinal(message.results);
  };
}

function globalClient(route) {
  const ws = openSocket(route);
  ws.onmessage = (event) => {
    const message = JSON.parse(event.data);
    renderStatus(message.state);
    renderGlobal(message.state);
  };
}

function adminClient() {
  const ws = openSocket('/admin');
  document.querySelector('#start').onclick = () => ws.send(JSON.stringify({ type: 'start' }));
  document.querySelector('#finish').onclick = () => ws.send(JSON.stringify({ type: 'finish' }));
  ws.onmessage = (event) => {
    const message = JSON.parse(event.data);
    renderStatus(message.state);
    renderGlobal(message.state);
  };
}

function replayClient() {
  const ws = openSocket('/replay');
  ws.onmessage = (event) => {
    const message = JSON.parse(event.data);
    document.querySelector('#status').innerHTML = `<span class="pill">Replay loaded</span>`;
    document.querySelector('#replay').innerHTML = `<pre>${escapeHtml(JSON.stringify(message.replay ?? message, null, 2))}</pre>`;
  };
}

function openSocket(route) {
  const scheme = location.protocol === 'https:' ? 'wss:' : 'ws:';
  latestSocket = new WebSocket(`${scheme}//${location.host}${route}`);
  return latestSocket;
}

function renderPlayer(view, ws) {
  renderStatus(view);
  renderBomb(view);
  renderChats(view);
  renderIntel(view);
}

function renderStatus(view) {
  const seconds = Math.ceil((view.timeRemainingMs ?? 0) / 1000);
  const status = document.querySelector('#status');
  if (!status) return;
  status.innerHTML = [
    `<span class="pill">${escapeHtml(view.phase ?? (view.started ? 'playing' : 'lobby'))}</span>`,
    `<span class="pill">${seconds}s</span>`,
    view.slot !== undefined ? `<span class="pill">P${view.slot + 1}</span>` : '',
    view.score !== undefined ? `<span class="pill">Score ${view.score}</span>` : '',
    view.lobby ? `<span class="pill">${view.lobby.readyCount}/${view.lobby.requiredCount} ready</span>` : '',
  ].join('');
}

function renderBomb(view, ws) {
  const bomb = document.querySelector('#bomb');
  if (!bomb) return;
  if (view.phase === 'lobby') {
    const html = `
      <section class="module">
        <h3>Lobby</h3>
        <p>${view.lobby.connectedCount}/${view.lobby.requiredCount} connected. ${view.lobby.readyCount}/${view.lobby.requiredCount} ready.</p>
        <button data-ready="${view.ready ? 'false' : 'true'}">${view.ready ? 'Unready' : 'Ready'}</button>
      </section>
    `;
    if (uiState.bombKey !== html) {
      uiState.bombKey = html;
      bomb.innerHTML = html;
    }
    return;
  }
  if (view.bomb.detonated) {
    const html = `<h3 class="detonated">Detonated</h3><p>${escapeHtml(view.bomb.detonationReason ?? '')}</p>`;
    if (uiState.bombKey !== html) {
      uiState.bombKey = html;
      bomb.innerHTML = html;
    }
    return;
  }
  const modules = visibleModules(view.bomb.modules);
  const key = JSON.stringify(
    modules.map((module) => ({
      id: module.id,
      kind: module.kind,
      instance: module.instance,
      status: module.status,
      lethal: module.lethal,
      points: module.points,
      timed: module.timed,
      wires: module.wires,
      symbols: module.symbols,
      choices: module.choices,
      choice: module.choice,
      rpsResult: module.rpsResult,
      claims: module.claims,
      switches: module.switches,
      initialCode: module.initialCode,
      route: module.route,
      targets: module.targets,
      votes: module.votes,
      calculatorResults: module.kind === 'telephone_relay' ? view.calculatorResults : undefined,
    })),
  );
  if (uiState.bombKey !== key) {
    uiState.bombKey = key;
    bomb.innerHTML = `
      <div class="bomb-case">
        <div class="case-latch top-left"></div>
        <div class="case-latch top-right"></div>
        <div class="case-latch bottom-left"></div>
        <div class="case-latch bottom-right"></div>
        <div class="bomb-grid">
          ${modules.map((module) => renderModule(module, view.metaManuals[module.kind] ?? '', view)).join('')}
        </div>
      </div>
    `;
  }
  updateModuleTimers(modules);
}

function renderModule(module, meta, view) {
  const timer = module.timed
    ? `<span data-timer="${escapeHtml(module.id)}">${Math.max(0, Math.ceil((module.expiresAt - Date.now()) / 1000))}s</span>`
    : '<span>untimed</span>';
  const controls = module.status === 'active' || module.kind === 'telephone_relay' ? moduleControls(module) : '';
  return `
    <article class="module module-${module.kind} ${module.status}">
      <div class="module-head">
        <h3>${lethalityIcon(module)} ${escapeHtml(module.name)}</h3>
        <details class="manual" data-module="${escapeHtml(module.id)}" ${uiState.manualOpen.has(module.id) ? 'open' : ''}><summary aria-label="Meta-manual">?</summary><p>${escapeHtml(meta)}</p></details>
      </div>
      <p class="module-meta"><span class="status-light ${escapeHtml(module.status)}"></span><span>${escapeHtml(module.status)}</span>${module.lethal ? '<span class="detonated">lethal</span>' : '<span class="ok">non-lethal</span>'} <span>${module.points} pts</span> ${timer}</p>
      ${controls}
    </article>
  `;

  function moduleControls(mod) {
    if (mod.kind === 'wire_cut') {
      return `<div class="wire-bank">${mod.wires.map((wire) => `<button class="wire-button wire-${escapeHtml(wire)}" data-op="${mod.id}" data-action='${jsonAttr({ wire })}'><span></span>${escapeHtml(wire)}</button>`).join('')}</div>`;
    }
    if (mod.kind === 'keypad_calibration') {
      return `<div class="keypad-grid">${mod.symbols.map((answer) => `<button data-op="${mod.id}" data-action='${jsonAttr({ answer })}'>${escapeHtml(answer)}</button>`).join('')}</div>`;
    }
    if (mod.kind === 'switch_panel') {
      return `<form class="actions" data-switch="${mod.id}">
        <select name="a"><option value="true">1 ON</option><option value="false">1 OFF</option></select>
        <select name="b"><option value="true">2 ON</option><option value="false">2 OFF</option></select>
        <select name="c"><option value="true">3 ON</option><option value="false">3 OFF</option></select>
        <button>Set</button>
      </form>`;
    }
    if (mod.kind === 'rps_duel') {
      const partner = `<p class="module-note">Partner: Player ${mod.opponentSlot + 1}</p>`;
      if (mod.rpsResult) {
        return `${partner}<p class="rps-result">${escapeHtml(mod.rpsResult)}</p>`;
      }
      if (mod.choice) {
        return `${partner}<p class="muted">Selected ${escapeHtml(mod.choice)}. Resolves at round end.</p>`;
      }
      return `${partner}<div class="rps-row">${mod.choices.map((choice) => `<button data-op="${mod.id}" data-action='${jsonAttr({ choice })}'>${escapeHtml(choice)}</button>`).join('')}</div>`;
    }
    if (mod.kind === 'two_truths_lie') {
      return `<div class="claims-row">${[1, 2, 3].map((falseClaim) => `<button data-op="${mod.id}" data-action='${jsonAttr({ falseClaim })}'>Claim ${falseClaim}</button>`).join('')}</div>`;
    }
    if (mod.kind === 'telephone_relay') {
      return `
        <div class="telephone-instructions">
          <p>Start <strong>${escapeHtml(mod.initialCode)}</strong></p>
          <p>${mod.route.map((slot) => `P${slot + 1}`).join(' -> ')} -> P${mod.targetSlot + 1}</p>
        </div>
        <div class="calculator-card module-calculator">
          <form data-calculate>
            <input name="code" inputmode="numeric" pattern="[0-9]{4}" maxlength="4" placeholder="0000" />
            <button>Run</button>
          </form>
          <div class="calculator-results">
            ${(view.calculatorResults ?? [])
              .slice()
              .reverse()
              .map((result) => `<span>${escapeHtml(result.input)} -> <strong>${escapeHtml(result.output)}</strong></span>`)
              .join('')}
          </div>
        </div>
        ${
          mod.status === 'active'
            ? `<form class="telephone-entry" data-telephone="${escapeHtml(mod.id)}">
                <input name="code" inputmode="numeric" pattern="[0-9]{4}" maxlength="4" placeholder="0000" />
                <button>Submit</button>
              </form>`
            : ''
        }
      `;
    }
    if (mod.kind === 'coup') {
      return `
        <div class="coup-grid">
          ${mod.targets
            .map((target) => {
              const active = mod.votes.includes(target);
              return `<button class="${active ? 'selected' : ''}" data-op="${mod.id}" data-action='${jsonAttr({ target })}'>P${target + 1}${active ? ' coup' : ''}</button>`;
            })
            .join('')}
        </div>
      `;
    }
    return '';
  }
}

function visibleModules(modules) {
  const byKind = new Map();
  for (const module of modules) {
    const existing = byKind.get(module.kind);
    if (!existing || module.instance > existing.instance) byKind.set(module.kind, module);
  }
  return [...byKind.values()].sort((a, b) => moduleOrder(a.kind) - moduleOrder(b.kind) || a.kind.localeCompare(b.kind));
}

function moduleOrder(kind) {
  const order = ['wire_cut', 'keypad_calibration', 'switch_panel', 'rps_duel', 'two_truths_lie', 'telephone_relay', 'coup'].indexOf(kind);
  return order === -1 ? 999 : order;
}

function updateModuleTimers(modules) {
  for (const module of modules) {
    if (!module.timed) continue;
    const timer = document.querySelector(`[data-timer="${cssEscape(module.id)}"]`);
    if (timer) timer.textContent = `${Math.max(0, Math.ceil((module.expiresAt - Date.now()) / 1000))}s`;
  }
}

function lethalityIcon(module) {
  return module.lethal
    ? '<span class="lethality lethal" title="Lethal">☠️</span>'
    : '<span class="lethality nonlethal" title="Non-lethal"><span class="skull">☠️</span></span>';
}

function renderChats(view) {
  const chats = document.querySelector('#chats');
  if (!chats) return;
  if (view.phase === 'lobby') {
    const html = `<div class="chat-grid">${(view.communication?.neighbors ?? [])
      .map((neighbor) => `<section class="chat locked"><h3>Player ${neighbor + 1}</h3><div class="messages"><p class="muted">Lobby</p></div></section>`)
      .join('')}</div>`;
    if (uiState.chatsKey !== html) {
      uiState.chatsKey = html;
      chats.innerHTML = html;
    }
    return;
  }
  const focus = snapshotChatFocus();
  const key = JSON.stringify({
    neighbors: view.communication.neighbors,
    neighborStates: view.communication.neighborStates,
    messages: view.communication.directMessages.map((message) => [message.id, message.from, message.to, message.text]),
  });
  if (uiState.chatsKey === key) return;
  uiState.chatsKey = key;
  chats.innerHTML = `<div class="chat-grid">${view.communication.neighbors
    .map((neighbor) => {
      const neighborState = view.communication.neighborStates?.find((state) => state.slot === neighbor);
      if (neighborState?.detonated) return renderDeadChatPanel(neighbor, neighborState);
      const messages = view.communication.directMessages.filter((message) => message.from === neighbor || message.to === neighbor);
      return `
          <section class="chat">
            <h3>Player ${neighbor + 1}</h3>
            <div class="messages">${messages
              .map((message) => `<div class="message"><small>P${message.from + 1}</small> ${escapeHtml(message.text)}</div>`)
              .join('')}</div>
            <form data-chat="${neighbor}">
              <input name="text" autocomplete="off" />
              <button>Send</button>
            </form>
          </section>
        `;
    })
    .join('')}</div>`;
  restoreChatInputs(focus);
}

function renderDeadChatPanel(neighbor, neighborState) {
  const hints = neighborState.revealedHintsForYou ?? [];
  return `
    <section class="chat dead-chat">
      <h3>Player ${neighbor + 1} detonated</h3>
      <div class="dead-chat-hints">
        ${
          hints.length
            ? hints
                .map(
                  (hint) => `
                    <div class="dead-hint">
                      <small>${escapeHtml(hint.moduleKind.replaceAll('_', ' '))}${hint.moduleInstance > 1 ? ` p${hint.moduleInstance}` : ''}</small>
                      <p>${escapeHtml(shortHint(hint.text))}</p>
                    </div>
                  `,
                )
                .join('')
            : '<p class="muted">No recovered hints for your bomb.</p>'
        }
      </div>
    </section>
  `;
}

function renderIntel(view) {
  const intel = document.querySelector('#intel');
  if (!intel) return;
  if (view.phase === 'lobby') {
    const html = '<p class="muted intel-empty">Manual intel appears when the game starts.</p>';
    if (uiState.intelKey !== html) {
      uiState.intelKey = html;
      intel.innerHTML = html;
    }
    return;
  }
  const orderedGroups = orderHintGroups(groupHintsByTarget(view.hints), view.communication?.neighbors ?? []);
  const key = JSON.stringify(orderedGroups);
  if (uiState.intelKey === key) return;
  uiState.intelKey = key;
  intel.innerHTML = `
    <div class="intel-grid">
      ${orderedGroups
        .map(
          (group) => `
            <section class="intel-card">
              ${
                group.modules.length
                  ? group.modules
                      .map(
                        (module) => `
                          <div class="intel-module">
                            <strong>${escapeHtml(module.kindLabel)}</strong>
                            <ul>${module.hints
                              .map((hint) => `<li>${escapeHtml(hint.phaseLabel ? `${hint.phaseLabel}: ${shortHint(hint.text)}` : shortHint(hint.text))}</li>`)
                              .join('')}</ul>
                          </div>
                        `,
                      )
                      .join('')
                  : '<p class="muted intel-empty">No held hints.</p>'
              }
            </section>
          `,
        )
        .join('')}
    </div>
  `;
}

function groupHintsByTarget(hints) {
  const targets = new Map();
  for (const hint of hints) {
    if (!targets.has(hint.targetSlot)) targets.set(hint.targetSlot, new Map());
    const modules = targets.get(hint.targetSlot);
    const key = hint.moduleKind;
    if (!modules.has(key)) {
      modules.set(key, {
        kind: hint.moduleKind,
        kindLabel: hint.moduleKind.replaceAll('_', ' '),
        hints: [],
        instances: new Set(),
      });
    }
    const module = modules.get(key);
    module.instances.add(hint.moduleInstance);
    module.hints.push(hint);
  }
  return [...targets.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([target, modules]) => ({
      target,
      modules: [...modules.values()]
        .map((module) => ({
          kind: module.kind,
          kindLabel: module.kindLabel,
          hints: module.hints
            .sort((a, b) => a.moduleInstance - b.moduleInstance || a.id.localeCompare(b.id))
            .map((hint) => ({
              ...hint,
              phaseLabel: module.instances.size > 1 ? `p${hint.moduleInstance}` : '',
            })),
        }))
        .sort((a, b) => moduleOrder(a.kind) - moduleOrder(b.kind) || a.kind.localeCompare(b.kind)),
    }));
}

function orderHintGroups(groups, neighbors) {
  const byTarget = new Map(groups.map((group) => [group.target, group]));
  const ordered = neighbors.map((slot) => byTarget.get(slot) ?? { target: slot, modules: [] });
  for (const group of groups) {
    if (!neighbors.includes(group.target)) ordered.push(group);
  }
  return ordered;
}

function shortHint(text) {
  return String(text).replace(/^Claim \d+:\s*/i, '').replace(/^The /, '');
}

function renderGlobal(state) {
  const global = document.querySelector('#global');
  if (!global) return;
  global.innerHTML = `
    <section class="spectator-main only-bombs">
      <div class="spectator-bomb-stage">
        <div class="spectator-bombs">
          ${state.bombs.map((bomb) => renderSpectatorBomb(bomb, state.scores[bomb.slot])).join('')}
        </div>
        <svg class="message-pulses" aria-hidden="true"></svg>
      </div>
    </section>
  `;
  updateMessagePulses(state);
}

function renderSpectatorBomb(bomb, score) {
  const modules = visibleModules(bomb.modules);
  return `
    <article class="spectator-bomb ${bomb.detonated ? 'dead' : 'alive'}" data-player="${bomb.slot}">
      <header>
        <h3>P${bomb.slot + 1}</h3>
        <span>${score} pts</span>
        <small>${bomb.detonated ? escapeHtml(bomb.detonationReason ?? 'detonated') : bombSummary(bomb)}</small>
      </header>
      <div class="spectator-modules">
        ${modules
          .map(
            (module) => `
              <div class="spectator-module ${escapeHtml(module.status)} ${module.lethal ? 'lethal-card' : ''}">
                <strong>${escapeHtml(module.name)}</strong>
                <span>${escapeHtml(module.status)}</span>
                ${module.timed && module.status === 'active' ? `<b>${Math.max(0, Math.ceil((module.expiresAt - Date.now()) / 1000))}s</b>` : ''}
                ${module.kind === 'telephone_relay' ? `<em>${module.route.map((slot) => `P${slot + 1}`).join(' -> ')}</em>` : ''}
                ${module.kind === 'rps_duel' ? `<em>Partner: P${module.opponentSlot + 1}</em>` : ''}
                ${module.kind === 'coup' && module.votes?.length ? `<em>Couping: ${module.votes.map((slot) => `P${slot + 1}`).join(', ')}</em>` : ''}
                ${module.rpsResult ? `<em>${escapeHtml(module.rpsResult)}</em>` : ''}
              </div>
            `,
          )
          .join('')}
      </div>
    </article>
  `;
}

function bombSummary(bomb) {
  const active = bomb.modules.filter((module) => module.status === 'active').length;
  const solved = bomb.modules.filter((module) => module.status === 'solved').length;
  const urgent = bomb.modules
    .filter((module) => module.status === 'active' && module.timed)
    .map((module) => Math.max(0, Math.ceil((module.expiresAt - Date.now()) / 1000)))
    .sort((a, b) => a - b)[0];
  return `${solved} solved, ${active} active${urgent !== undefined ? `, ${urgent}s min` : ''}`;
}

function updateMessagePulses(state) {
  const stage = document.querySelector('.spectator-bomb-stage');
  const svg = stage?.querySelector('.message-pulses');
  if (!stage || !svg) return;
  const stageRect = stage.getBoundingClientRect();
  svg.setAttribute('viewBox', `0 0 ${Math.max(1, stageRect.width)} ${Math.max(1, stageRect.height)}`);
  const recent = state.recentEvents
    .filter((event) => event.type === 'direct_chat' && Date.now() - event.at < 4500)
    .slice(-12);
  svg.innerHTML = recent
    .map((event) => {
      const fromCard = stage.querySelector(`[data-player="${cssEscape(event.data.from)}"]`);
      const toCard = stage.querySelector(`[data-player="${cssEscape(event.data.to)}"]`);
      if (!fromCard || !toCard) return '';
      const fromRect = fromCard.getBoundingClientRect();
      const toRect = toCard.getBoundingClientRect();
      const [x1, y1] = edgeAnchor(fromRect, toRect, stageRect);
      const [x2, y2] = edgeAnchor(toRect, fromRect, stageRect);
      const age = Math.max(0, Date.now() - event.at);
      const opacity = Math.max(0.15, 1 - age / 4500).toFixed(2);
      return `<line class="message-pulse" x1="${x1.toFixed(1)}" y1="${y1.toFixed(1)}" x2="${x2.toFixed(1)}" y2="${y2.toFixed(1)}" style="--pulse-opacity:${opacity}" />`;
    })
    .join('');
}

function edgeAnchor(fromRect, toRect, stageRect) {
  const from = rectCenter(fromRect, stageRect);
  const to = rectCenter(toRect, stageRect);
  const dx = to[0] - from[0];
  const dy = to[1] - from[1];
  if (dx === 0 && dy === 0) return from;
  const inset = 12;
  const xScale = dx === 0 ? Infinity : Math.max(0, fromRect.width / 2 - inset) / Math.abs(dx);
  const yScale = dy === 0 ? Infinity : Math.max(0, fromRect.height / 2 - inset) / Math.abs(dy);
  const scale = Math.min(xScale, yScale, 1);
  return [from[0] + dx * scale, from[1] + dy * scale];
}

function rectCenter(rect, stageRect) {
  return [rect.left - stageRect.left + rect.width / 2, rect.top - stageRect.top + rect.height / 2];
}

function renderFinal(results) {
  document.body.innerHTML = `<main class="shell"><h1>Game Over</h1><pre>${escapeHtml(JSON.stringify(results, null, 2))}</pre></main>`;
}

document.addEventListener('click', (event) => {
  const button = event.target.closest('button[data-op], button[data-ready]');
  if (!button) return;
  const socket = currentSocket();
  if (!socket) return;
  if (button.dataset.ready) socket.send(JSON.stringify({ type: 'ready', ready: button.dataset.ready === 'true' }));
  if (button.dataset.op) socket.send(JSON.stringify({ type: 'operate', moduleId: button.dataset.op, action: JSON.parse(button.dataset.action) }));
});

document.addEventListener(
  'toggle',
  (event) => {
    const details = event.target.closest?.('details.manual[data-module]');
    if (!details) return;
    if (details.open) uiState.manualOpen.add(details.dataset.module);
    else uiState.manualOpen.delete(details.dataset.module);
  },
  true,
);

document.addEventListener('input', (event) => {
  const input = event.target.closest?.('form[data-chat] input[name="text"]');
  if (!input) return;
  uiState.chatDrafts.set(input.form.dataset.chat, input.value);
});

document.addEventListener('submit', (event) => {
  const form = event.target;
  const socket = currentSocket();
  if (!socket) return;
  if (form.dataset.chat) {
    event.preventDefault();
    socket.send(JSON.stringify({ type: 'chat', to: Number(form.dataset.chat), text: form.elements.text.value }));
    uiState.chatDrafts.delete(form.dataset.chat);
    form.reset();
  }
  if (form.dataset.switch) {
    event.preventDefault();
    socket.send(
      JSON.stringify({
        type: 'operate',
        moduleId: form.dataset.switch,
        action: { settings: [form.elements.a.value === 'true', form.elements.b.value === 'true', form.elements.c.value === 'true'] },
      }),
    );
  }
  if (form.dataset.telephone) {
    event.preventDefault();
    socket.send(JSON.stringify({ type: 'operate', moduleId: form.dataset.telephone, action: { code: form.elements.code.value } }));
    form.reset();
  }
  if (form.dataset.calculate !== undefined) {
    event.preventDefault();
    socket.send(JSON.stringify({ type: 'calculate', code: form.elements.code.value }));
    form.reset();
  }
});

function currentSocket() {
  return latestSocket;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);
}

function jsonAttr(value) {
  return escapeHtml(JSON.stringify(value));
}

function snapshotChatFocus() {
  const active = document.activeElement;
  if (!active?.matches?.('form[data-chat] input[name="text"]')) return null;
  return {
    chat: active.form.dataset.chat,
    start: active.selectionStart,
    end: active.selectionEnd,
  };
}

function restoreChatInputs(focus) {
  for (const [chat, value] of uiState.chatDrafts) {
    const input = document.querySelector(`form[data-chat="${cssEscape(chat)}"] input[name="text"]`);
    if (input) input.value = value;
  }
  if (!focus) return;
  const input = document.querySelector(`form[data-chat="${cssEscape(focus.chat)}"] input[name="text"]`);
  if (!input) return;
  input.focus();
  input.setSelectionRange(focus.start ?? input.value.length, focus.end ?? input.value.length);
}

function cssEscape(value) {
  if (window.CSS?.escape) return CSS.escape(String(value));
  return String(value).replace(/["\\]/g, '\\$&');
}
