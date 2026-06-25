import crypto from 'node:crypto';

const GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11';

export class WebSocketConnection {
  constructor(socket) {
    this.socket = socket;
    this.buffer = Buffer.alloc(0);
    this.closed = false;
    this.handlers = { message: new Set(), close: new Set(), error: new Set() };
    socket.on('data', (chunk) => this.#parse(chunk));
    socket.on('close', () => this.#emit('close'));
    socket.on('error', (error) => this.#emit('error', error));
  }

  on(event, handler) {
    this.handlers[event].add(handler);
  }

  off(event, handler) {
    this.handlers[event].delete(handler);
  }

  sendJson(value) {
    this.send(JSON.stringify(value));
  }

  send(text) {
    if (this.closed) return;
    const payload = Buffer.from(text);
    let header;
    if (payload.length < 126) {
      header = Buffer.from([0x81, payload.length]);
    } else if (payload.length <= 65535) {
      header = Buffer.alloc(4);
      header[0] = 0x81;
      header[1] = 126;
      header.writeUInt16BE(payload.length, 2);
    } else {
      header = Buffer.alloc(10);
      header[0] = 0x81;
      header[1] = 127;
      header.writeBigUInt64BE(BigInt(payload.length), 2);
    }
    this.socket.write(Buffer.concat([header, payload]));
  }

  close(code = 1000, reason = '') {
    if (this.closed) return;
    this.closed = true;
    const reasonBuffer = Buffer.from(reason);
    const payload = Buffer.alloc(2 + reasonBuffer.length);
    payload.writeUInt16BE(code, 0);
    reasonBuffer.copy(payload, 2);
    this.socket.write(frame(0x8, payload));
    this.socket.end();
  }

  #parse(chunk) {
    this.buffer = Buffer.concat([this.buffer, chunk]);
    while (this.buffer.length >= 2) {
      const opcode = this.buffer[0] & 0x0f;
      const masked = Boolean(this.buffer[1] & 0x80);
      let length = this.buffer[1] & 0x7f;
      let offset = 2;
      if (length === 126) {
        if (this.buffer.length < 4) return;
        length = this.buffer.readUInt16BE(2);
        offset = 4;
      } else if (length === 127) {
        if (this.buffer.length < 10) return;
        length = Number(this.buffer.readBigUInt64BE(2));
        offset = 10;
      }
      let mask = null;
      if (masked) {
        if (this.buffer.length < offset + 4) return;
        mask = this.buffer.subarray(offset, offset + 4);
        offset += 4;
      }
      if (this.buffer.length < offset + length) return;
      let payload = this.buffer.subarray(offset, offset + length);
      this.buffer = this.buffer.subarray(offset + length);
      if (mask) payload = Buffer.from(payload.map((byte, index) => byte ^ mask[index % 4]));
      if (opcode === 0x1) this.#emit('message', payload.toString('utf8'));
      if (opcode === 0x8) {
        this.closed = true;
        this.socket.end();
        this.#emit('close');
      }
      if (opcode === 0x9) this.socket.write(frame(0xa, payload));
    }
  }

  #emit(event, value) {
    for (const handler of this.handlers[event]) handler(value);
  }
}

export function handleUpgrade(request, socket, head, routes) {
  const url = new URL(request.url, 'http://localhost');
  const handler = routes[url.pathname];
  if (!handler) {
    socket.write('HTTP/1.1 404 Not Found\r\n\r\n');
    socket.destroy();
    return;
  }
  const key = request.headers['sec-websocket-key'];
  if (!key) {
    socket.write('HTTP/1.1 400 Bad Request\r\n\r\n');
    socket.destroy();
    return;
  }
  const accept = crypto.createHash('sha1').update(key + GUID).digest('base64');
  socket.write(
    [
      'HTTP/1.1 101 Switching Protocols',
      'Upgrade: websocket',
      'Connection: Upgrade',
      `Sec-WebSocket-Accept: ${accept}`,
      '\r\n',
    ].join('\r\n'),
  );
  const connection = new WebSocketConnection(socket);
  if (head?.length) connection.buffer = Buffer.concat([connection.buffer, head]);
  handler(connection, request, url);
}

function frame(opcode, payload) {
  return Buffer.concat([Buffer.from([0x80 | opcode, payload.length]), payload]);
}
