export const boardShader = `
@group(0) @binding(0) var spriteSampler: sampler;
@group(0) @binding(1) var spriteTexture: texture_2d<f32>;

struct VertexInput {
  @location(0) corner: vec2<f32>,
  @location(1) center: vec2<f32>,
  @location(2) size: vec2<f32>,
  @location(3) color: vec4<f32>,
  @location(4) uvRect: vec4<f32>,
  @location(5) textureMix: f32,
};

struct VertexOutput {
  @builtin(position) position: vec4<f32>,
  @location(0) color: vec4<f32>,
  @location(1) uv: vec2<f32>,
  @location(2) textureMix: f32,
  @location(3) local: vec2<f32>,
};

@vertex
fn vertexMain(input: VertexInput) -> VertexOutput {
  var output: VertexOutput;
  let xy = input.center + input.corner * input.size;
  let uvFactor = vec2<f32>(input.corner.x * 0.5 + 0.5, 0.5 - input.corner.y * 0.5);
  output.position = vec4<f32>(xy, 0.0, 1.0);
  output.color = input.color;
  output.uv = input.uvRect.xy + uvFactor * (input.uvRect.zw - input.uvRect.xy);
  output.textureMix = input.textureMix;
  output.local = input.corner;
  return output;
}

fn hueToRgb(hue: f32) -> vec3<f32> {
  let h = fract(hue);
  let r = abs(h * 6.0 - 3.0) - 1.0;
  let g = 2.0 - abs(h * 6.0 - 2.0);
  let b = 2.0 - abs(h * 6.0 - 4.0);
  return clamp(vec3<f32>(r, g, b), vec3<f32>(0.0), vec3<f32>(1.0));
}

fn partyHatRainbowColor(localY: f32) -> vec3<f32> {
  let vertical = clamp((localY + 1.0) * 0.5, 0.0, 0.999);
  let band = floor(vertical * 6.0) / 5.0;
  return hueToRgb(0.02 + band * 0.78);
}

@fragment
fn fragmentMain(input: VertexOutput) -> @location(0) vec4<f32> {
  let spriteColor = textureSample(spriteTexture, spriteSampler, input.uv);
  if (input.textureMix > 0.5) {
    return spriteColor;
  }

  if (input.textureMix < -3.5) {
    let halfWidth = max(0.0, (1.0 - input.local.y) * 0.5);
    let edgeAlpha = 1.0 - smoothstep(max(0.0, halfWidth - 0.05), halfWidth, abs(input.local.x));
    let baseAlpha = smoothstep(-1.0, -0.92, input.local.y);
    let tipAlpha = 1.0 - smoothstep(0.92, 1.0, input.local.y);
    return vec4<f32>(partyHatRainbowColor(input.local.y), input.color.a * edgeAlpha * baseAlpha * tipAlpha);
  }

  if (input.textureMix < -2.5) {
    let halfWidth = max(0.0, (1.0 - input.local.y) * 0.5);
    let edgeAlpha = 1.0 - smoothstep(max(0.0, halfWidth - 0.05), halfWidth, abs(input.local.x));
    let baseAlpha = smoothstep(-1.0, -0.92, input.local.y);
    let tipAlpha = 1.0 - smoothstep(0.92, 1.0, input.local.y);
    return vec4<f32>(input.color.rgb, input.color.a * edgeAlpha * baseAlpha * tipAlpha);
  }

  if (input.textureMix < -1.5) {
    let distance = length(input.local);
    let outerFade = 1.0 - smoothstep(0.84, 1.0, distance);
    let innerFade = smoothstep(0.52, 0.72, distance);
    return vec4<f32>(input.color.rgb, input.color.a * outerFade * innerFade);
  }

  if (input.textureMix < -0.5) {
    let distance = length(input.local);
    let alpha = input.color.a * (1.0 - smoothstep(0.78, 1.0, distance));
    return vec4<f32>(input.color.rgb, alpha);
  }

  return input.color;
}
`;
