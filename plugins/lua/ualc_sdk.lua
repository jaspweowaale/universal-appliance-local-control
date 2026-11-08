--[[
UALC Lua plugin SDK / sandbox host.

Invoked by the Python host (translator/lua_host.py) as:

    lua ualc_sdk.lua <handler.lua>

Speaks NDJSON on stdio: one JSON request object per line in, one JSON
response object per line out. See docs/PLUGIN_MANIFEST_SPEC.md for the wire
contract.

THIS FILE IS PART OF UALC CORE, NOT A PLUGIN. Community handlers are loaded
*by* this file into a restricted environment; they never replace it.

Sandbox note, stated honestly: the environment table below is the *inner*
layer of a two-layer design. It removes the obvious escapes (io, os.execute,
package/require/loadlib, debug, dofile) and loads the handler with mode "t"
so precompiled Lua bytecode cannot be injected. It is NOT by itself a
security boundary against hostile code -- the real boundary is the OS-level
one the Python host applies (separate process, rlimits, no filesystem writes,
no credentials ever sent). See docs/LUA_PLUGIN_ARCHITECTURE.md section 6.

MIT-licensed, part of this project's own code. No third-party Lua libraries
are vendored -- the JSON codec below is written for this project specifically
so that no external license applies.
]]

local HANDLER_PATH = arg and arg[1]
if not HANDLER_PATH then
  io.stderr:write("ualc_sdk: no handler path given\n")
  os.exit(2)
end

-- Capture the host-side primitives we need BEFORE building the sandbox, so
-- the handler cannot reach them even by name.
local real_io, real_os = io, os
local real_load = load
local sformat, sbyte, schar, ssub, sgsub, srep =
  string.format, string.byte, string.char, string.sub, string.gsub, string.rep
local tconcat, tinsert = table.concat, table.insert
local mfloor, mhuge = math.floor, math.huge

-- ---------------------------------------------------------------------------
-- Minimal JSON codec (ours; no third-party code)
-- ---------------------------------------------------------------------------

local json = {}

-- Marker so a handler can force [] rather than {} for an empty sequence.
local ARRAY_MT = {__ualc_array = true}
function json.array(t)
  return setmetatable(t or {}, ARRAY_MT)
end

local ESCAPES = {
  ['"'] = '\\"', ['\\'] = '\\\\', ['\b'] = '\\b', ['\f'] = '\\f',
  ['\n'] = '\\n', ['\r'] = '\\r', ['\t'] = '\\t',
}

local function esc(c)
  local e = ESCAPES[c]
  if e then return e end
  return sformat("\\u%04x", sbyte(c))
end

local function is_array(t)
  if getmetatable(t) == ARRAY_MT then return true end
  local n = 0
  for k in pairs(t) do
    if type(k) ~= "number" then return false end
    n = n + 1
  end
  if n == 0 then return false end          -- empty table encodes as {}
  for i = 1, n do
    if t[i] == nil then return false end   -- sparse -> treat as object
  end
  return true
end

local encode_value

local function encode_string(s)
  return '"' .. sgsub(s, '[%c"\\]', esc) .. '"'
end

local function encode_number(n)
  if n ~= n or n == mhuge or n == -mhuge then
    error("json: cannot encode non-finite number", 0)
  end
  if mfloor(n) == n and n >= -9007199254740992 and n <= 9007199254740992 then
    return sformat("%d", n)
  end
  return sformat("%.17g", n)
end

local function encode_table(t, depth)
  if depth > 24 then error("json: nesting too deep", 0) end
  local out = {}
  if is_array(t) then
    for i = 1, #t do
      out[#out + 1] = encode_value(t[i], depth + 1)
    end
    return "[" .. tconcat(out, ",") .. "]"
  end
  -- Deterministic key order: reproducible output makes fixtures stable.
  local keys = {}
  for k in pairs(t) do
    if type(k) ~= "string" then
      error("json: object keys must be strings, got " .. type(k), 0)
    end
    keys[#keys + 1] = k
  end
  table.sort(keys)
  for i = 1, #keys do
    local k = keys[i]
    out[#out + 1] = encode_string(k) .. ":" .. encode_value(t[k], depth + 1)
  end
  return "{" .. tconcat(out, ",") .. "}"
end

encode_value = function(v, depth)
  local tv = type(v)
  if v == nil then return "null"
  elseif tv == "boolean" then return v and "true" or "false"
  elseif tv == "number" then return encode_number(v)
  elseif tv == "string" then return encode_string(v)
  elseif tv == "table" then return encode_table(v, depth)
  end
  error("json: cannot encode " .. tv, 0)
end

function json.encode(v)
  return encode_value(v, 0)
end

-- Decoder -------------------------------------------------------------------

local function dec_error(s, i, msg)
  error(sformat("json: %s at byte %d", msg, i), 0)
end

local UNESCAPES = {
  ['"'] = '"', ['\\'] = '\\', ['/'] = '/', b = '\b',
  f = '\f', n = '\n', r = '\r', t = '\t',
}

local parse_value

local function skip_ws(s, i)
  local _, j = s:find("^[ \t\r\n]*", i)
  return (j or i - 1) + 1
end

local function parse_string(s, i)
  i = i + 1
  local buf = {}
  while true do
    local c = ssub(s, i, i)
    if c == "" then dec_error(s, i, "unterminated string") end
    if c == '"' then return tconcat(buf), i + 1 end
    if c == "\\" then
      local n = ssub(s, i + 1, i + 1)
      local u = UNESCAPES[n]
      if u then
        buf[#buf + 1] = u
        i = i + 2
      elseif n == "u" then
        local hex = ssub(s, i + 2, i + 5)
        if not hex:match("^%x%x%x%x$") then dec_error(s, i, "bad \\u escape") end
        local cp = tonumber(hex, 16)
        -- Our contract is ASCII/hex-string oriented; encode BMP as UTF-8.
        if cp < 0x80 then
          buf[#buf + 1] = schar(cp)
        elseif cp < 0x800 then
          buf[#buf + 1] = schar(0xC0 + mfloor(cp / 0x40), 0x80 + cp % 0x40)
        else
          buf[#buf + 1] = schar(0xE0 + mfloor(cp / 0x1000),
                                0x80 + mfloor(cp % 0x1000 / 0x40),
                                0x80 + cp % 0x40)
        end
        i = i + 6
      else
        dec_error(s, i, "bad escape")
      end
    else
      buf[#buf + 1] = c
      i = i + 1
    end
  end
end

local function parse_number(s, i)
  local j = s:find("[^%-%+%.eE0-9]", i) or (#s + 1)
  local num = tonumber(ssub(s, i, j - 1))
  if not num then dec_error(s, i, "bad number") end
  return num, j
end

parse_value = function(s, i, depth)
  if depth > 24 then dec_error(s, i, "nesting too deep") end
  i = skip_ws(s, i)
  local c = ssub(s, i, i)
  if c == "{" then
    local obj = {}
    i = skip_ws(s, i + 1)
    if ssub(s, i, i) == "}" then return obj, i + 1 end
    while true do
      i = skip_ws(s, i)
      if ssub(s, i, i) ~= '"' then dec_error(s, i, "expected key") end
      local k; k, i = parse_string(s, i)
      i = skip_ws(s, i)
      if ssub(s, i, i) ~= ":" then dec_error(s, i, "expected ':'") end
      local v; v, i = parse_value(s, i + 1, depth + 1)
      obj[k] = v
      i = skip_ws(s, i)
      local d = ssub(s, i, i)
      if d == "}" then return obj, i + 1 end
      if d ~= "," then dec_error(s, i, "expected ',' or '}'") end
      i = i + 1
    end
  elseif c == "[" then
    local arr = json.array({})
    i = skip_ws(s, i + 1)
    if ssub(s, i, i) == "]" then return arr, i + 1 end
    while true do
      local v; v, i = parse_value(s, i, depth + 1)
      arr[#arr + 1] = v
      i = skip_ws(s, i)
      local d = ssub(s, i, i)
      if d == "]" then return arr, i + 1 end
      if d ~= "," then dec_error(s, i, "expected ',' or ']'") end
      i = i + 1
    end
  elseif c == '"' then
    return parse_string(s, i)
  elseif ssub(s, i, i + 3) == "true" then return true, i + 4
  elseif ssub(s, i, i + 4) == "false" then return false, i + 5
  elseif ssub(s, i, i + 3) == "null" then return nil, i + 4
  elseif c:match("[%-0-9]") then
    return parse_number(s, i)
  end
  dec_error(s, i, "unexpected character '" .. c .. "'")
end

function json.decode(s)
  local v, i = parse_value(s, 1, 0)
  i = skip_ws(s, i)
  if i <= #s then dec_error(s, i, "trailing data") end
  return v
end

-- ---------------------------------------------------------------------------
-- Helpers offered to handlers (the `ualc` table)
-- ---------------------------------------------------------------------------

local ualc = {}
ualc.API_VERSION = "1.0"
ualc.array = json.array

-- Hex <-> byte-array. The wire contract carries binary as lowercase hex
-- strings, because JSON has no byte type.
function ualc.hex_to_bytes(hex)
  if type(hex) ~= "string" then error("hex_to_bytes: expected string", 0) end
  if #hex % 2 ~= 0 then error("hex_to_bytes: odd-length hex", 0) end
  if hex ~= "" and not hex:match("^%x+$") then
    error("hex_to_bytes: non-hex characters", 0)
  end
  local out = {}
  for i = 1, #hex, 2 do
    out[#out + 1] = tonumber(ssub(hex, i, i + 1), 16)
  end
  return out
end

function ualc.bytes_to_hex(bytes)
  local out = {}
  for i = 1, #bytes do
    local b = bytes[i]
    if type(b) ~= "number" or b < 0 or b > 255 or mfloor(b) ~= b then
      error("bytes_to_hex: byte " .. i .. " out of range", 0)
    end
    out[i] = sformat("%02x", b)
  end
  return tconcat(out)
end

-- Structured failure a handler can raise. The host turns this into
-- {"ok":false,"error":{...}} rather than an opaque crash.
local ERROR_CODES = {
  UNSUPPORTED_MODEL = true, UNSUPPORTED_PROTOCOL_VERSION = true,
  MALFORMED_FRAME = true, UNSUPPORTED_COMMAND = true, INVALID_PARAMS = true,
  FIRMWARE_INCOMPATIBLE = true, NOT_IMPLEMENTED = true, INTERNAL_ERROR = true,
}

function ualc.fail(code, message, details)
  if not ERROR_CODES[code] then
    code, message = "INTERNAL_ERROR", "handler raised unknown code: " .. tostring(code)
  end
  error({__ualc_error = true, code = code, message = message or "", details = details}, 0)
end

ualc.ERROR_CODES = ERROR_CODES

-- ---------------------------------------------------------------------------
-- Sandbox environment
-- ---------------------------------------------------------------------------
-- Deliberately absent: io, package, require, dofile, loadfile, load,
-- loadstring, debug, collectgarbage, os.execute, os.getenv, os.remove,
-- os.rename, os.tmpname, os.exit, arg.
local function build_env()
  local env = {
    assert = assert, error = error, ipairs = ipairs, next = next,
    pairs = pairs, pcall = pcall, select = select, tonumber = tonumber,
    tostring = tostring, type = type, xpcall = xpcall, rawequal = rawequal,
    rawget = rawget, rawlen = rawlen, rawset = rawset,
    setmetatable = setmetatable, getmetatable = getmetatable,
    unpack = table.unpack,
    coroutine = coroutine,
    math = math,
    string = string,
    table = table,
    utf8 = utf8,
    -- Time only, for handlers that need relative timing. No clock setting,
    -- no environment, no process control, no filesystem.
    os = {time = real_os.time, clock = real_os.clock, difftime = real_os.difftime},
    ualc = ualc,
    json = {encode = json.encode, decode = json.decode, array = json.array},
  }
  env._G = env
  return env
end

-- ---------------------------------------------------------------------------
-- Load the handler
-- ---------------------------------------------------------------------------

local function read_file(path)
  local f, err = real_io.open(path, "rb")
  if not f then return nil, tostring(err) end
  local src = f:read("a")
  f:close()
  return src
end

local src, read_err = read_file(HANDLER_PATH)
if not src then
  real_io.stderr:write("ualc_sdk: cannot read handler: " .. tostring(read_err) .. "\n")
  os.exit(3)
end

-- Reject precompiled bytecode explicitly as well as via mode "t": a hostile
-- plugin shipping bytecode is a known Lua sandbox-escape vector.
if ssub(src, 1, 1) == "\27" then
  real_io.stderr:write("ualc_sdk: handler is precompiled bytecode; refused\n")
  os.exit(4)
end

local env = build_env()
local chunk, load_err = real_load(src, "@" .. HANDLER_PATH, "t", env)
if not chunk then
  real_io.stderr:write("ualc_sdk: handler failed to compile: " .. tostring(load_err) .. "\n")
  os.exit(5)
end

local ok, handler = pcall(chunk)
if not ok then
  real_io.stderr:write("ualc_sdk: handler failed to initialise: " .. tostring(handler) .. "\n")
  os.exit(6)
end
if type(handler) ~= "table" then
  real_io.stderr:write("ualc_sdk: handler must return a table of operations\n")
  os.exit(7)
end

-- ---------------------------------------------------------------------------
-- Request loop
-- ---------------------------------------------------------------------------

-- Every op is optional. `describe` is synthesised from the handler's own keys
-- if it does not provide one, so a plugin declares what it supports rather
-- than the host assuming a fixed surface.
local DISPATCHABLE = {
  identify = true, describe = true, parse_inbound = true, build_outbound = true,
  supported_commands = true, validate_command = true, is_ack_for = true,
  decode_state = true, describe_controls = true,
}

local function default_describe()
  local ops = json.array({})
  local names = {}
  for k in pairs(handler) do
    if DISPATCHABLE[k] then names[#names + 1] = k end
  end
  table.sort(names)
  for i = 1, #names do ops[i] = names[i] end
  return {api_version = ualc.API_VERSION, operations = ops}
end

local function respond(obj)
  real_io.stdout:write(json.encode(obj), "\n")
  real_io.stdout:flush()
end

local function handle(req)
  local id = req.id
  local op = req.op
  if type(op) ~= "string" then
    return {id = id, ok = false,
            error = {code = "INVALID_PARAMS", message = "missing op"}}
  end

  if op == "describe" and not handler.describe then
    return {id = id, ok = true, result = default_describe()}
  end

  local fn = DISPATCHABLE[op] and handler[op]
  if not fn then
    return {id = id, ok = false,
            error = {code = "NOT_IMPLEMENTED",
                     message = "handler does not implement '" .. op .. "'"}}
  end

  local okc, res = pcall(fn, req.args or {})
  if okc then
    return {id = id, ok = true, result = res}
  end
  if type(res) == "table" and res.__ualc_error then
    return {id = id, ok = false,
            error = {code = res.code, message = res.message, details = res.details}}
  end
  return {id = id, ok = false,
          error = {code = "INTERNAL_ERROR", message = tostring(res)}}
end

for line in real_io.lines() do
  if line ~= "" then
    local okd, req = pcall(json.decode, line)
    if not okd or type(req) ~= "table" then
      respond({id = nil, ok = false,
               error = {code = "INVALID_PARAMS",
                        message = "unparseable request line"}})
    else
      local oke, resp = pcall(handle, req)
      if oke then
        -- Encoding can itself fail if a handler returned something unencodable.
        local oke2, enc_err = pcall(respond, resp)
        if not oke2 then
          respond({id = req.id, ok = false,
                   error = {code = "INTERNAL_ERROR",
                            message = "result not encodable: " .. tostring(enc_err)}})
        end
      else
        respond({id = req.id, ok = false,
                 error = {code = "INTERNAL_ERROR", message = tostring(resp)}})
      end
    end
  end
end
