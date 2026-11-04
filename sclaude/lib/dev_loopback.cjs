// Loaded into a feature's dev server with NODE_OPTIONS=--require (dev_net_env
// in worktree.sh): a server that would listen on every interface listens on
// 127.0.0.1 instead.
//
// sclaude-proxy is the way in to a feature: it answers only this machine and
// the tailnet, and reaches the feature's own port on 127.0.0.1. A dev command
// left to itself (`next dev`, `next start`) listens on every interface, which
// would let anybody on the same network open the feature's port past that
// filter. Which command a product runs is its own business, so the address is
// set here, under every Node server the command starts, rather than in it.
//
// Only the wildcard is moved. An address the product names on purpose, a unix
// socket or a handle is left as it was.
"use strict";

const net = require("net");

const LOOPBACK = "127.0.0.1";
const WILDCARD = new Set(["", "0.0.0.0", "::", "::0", "[::]", "0:0:0:0:0:0:0:0"]);

function wildcard(host) {
  return host === undefined || host === null || WILDCARD.has(String(host));
}

function isPort(value) {
  return typeof value === "number" || (typeof value === "string" && /^\d+$/.test(value));
}

const listen = net.Server.prototype.listen;

net.Server.prototype.listen = function (...args) {
  const first = args[0];
  if (isPort(first)) {
    // listen(port[, host][, backlog][, callback])
    if (typeof args[1] === "string") {
      if (wildcard(args[1])) args[1] = LOOPBACK;
    } else {
      args.splice(1, 0, LOOPBACK);
    }
  } else if (first && typeof first === "object" && !Array.isArray(first)
             && first.path === undefined && first.fd === undefined
             && first.handle === undefined && first._handle === undefined) {
    // listen(options[, callback]) on a port: a port left out or undefined is
    // port 0, on every interface too.
    if (wildcard(first.host)) args[0] = Object.assign({}, first, { host: LOOPBACK });
  } else if (first === undefined || typeof first === "function") {
    // listen([callback]): a random port on every interface.
    args.unshift(0, LOOPBACK);
  }
  return listen.apply(this, args);
};
