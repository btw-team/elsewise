import Ajv2020, {
  type ErrorObject,
  type ValidateFunction,
} from "ajv/dist/2020.js";
import addFormats from "ajv-formats";

import clientHelloSchema from "../../../protocol/schemas/client.hello.schema.json";
import heartbeatAckSchema from "../../../protocol/schemas/heartbeat.ack.schema.json";
import heartbeatSchema from "../../../protocol/schemas/heartbeat.schema.json";
import eventAckSchema from "../../../protocol/schemas/event.ack.schema.json";
import evidenceEmitSchema from "../../../protocol/schemas/evidence.emit.schema.json";
import pairingApprovedSchema from "../../../protocol/schemas/pairing.approved.schema.json";
import pairingCancelSchema from "../../../protocol/schemas/pairing.cancel.schema.json";
import pairingCancelledSchema from "../../../protocol/schemas/pairing.cancelled.schema.json";
import pairingDeniedSchema from "../../../protocol/schemas/pairing.denied.schema.json";
import pairingErrorSchema from "../../../protocol/schemas/pairing.error.schema.json";
import pairingExpiredSchema from "../../../protocol/schemas/pairing.expired.schema.json";
import pairingPendingSchema from "../../../protocol/schemas/pairing.pending.schema.json";
import pairingRequestSchema from "../../../protocol/schemas/pairing.request.schema.json";
import protocolErrorSchema from "../../../protocol/schemas/protocol.error.schema.json";
import serverHelloSchema from "../../../protocol/schemas/server.hello.schema.json";
import sourceCommandAckSchema from "../../../protocol/schemas/source.command_ack.schema.json";
import sourceDiscoveredSchema from "../../../protocol/schemas/source.discovered.schema.json";
import sourceHealthSchema from "../../../protocol/schemas/source.health.schema.json";
import sourceStartSchema from "../../../protocol/schemas/source.start.schema.json";
import sourceStopSchema from "../../../protocol/schemas/source.stop.schema.json";
import uiEventSchema from "../../../protocol/schemas/ui.event.schema.json";
import type { ProtocolMessageMap, ProtocolMessageType } from "./models";

const ajv = new Ajv2020({ allErrors: true, strict: true });
addFormats(ajv);

const validators: {
  [Type in ProtocolMessageType]: ValidateFunction<ProtocolMessageMap[Type]>;
} = {
  "pairing.request": ajv.compile<PairingRequest>(pairingRequestSchema),
  "pairing.cancel": ajv.compile<PairingCancel>(pairingCancelSchema),
  "pairing.pending": ajv.compile<PairingPending>(pairingPendingSchema),
  "pairing.approved": ajv.compile<PairingApproved>(pairingApprovedSchema),
  "pairing.denied": ajv.compile<PairingDenied>(pairingDeniedSchema),
  "pairing.expired": ajv.compile<PairingExpired>(pairingExpiredSchema),
  "pairing.cancelled": ajv.compile<PairingCancelled>(pairingCancelledSchema),
  "pairing.error": ajv.compile<PairingError>(pairingErrorSchema),
  "client.hello": ajv.compile<ClientHello>(clientHelloSchema),
  "server.hello": ajv.compile<ServerHello>(serverHelloSchema),
  heartbeat: ajv.compile<Heartbeat>(heartbeatSchema),
  "heartbeat.ack": ajv.compile<HeartbeatAck>(heartbeatAckSchema),
  "source.discovered": ajv.compile<SourceDiscovered>(sourceDiscoveredSchema),
  "source.health": ajv.compile<SourceHealth>(sourceHealthSchema),
  "evidence.emit": ajv.compile<EvidenceEmit>(evidenceEmitSchema),
  "event.ack": ajv.compile<EventAck>(eventAckSchema),
  "source.start": ajv.compile<SourceCommand>(sourceStartSchema),
  "source.stop": ajv.compile<SourceCommand>(sourceStopSchema),
  "source.command_ack": ajv.compile<SourceCommandAck>(sourceCommandAckSchema),
  "ui.event": ajv.compile<UiEvent>(uiEventSchema),
  "protocol.error": ajv.compile<ProtocolError>(protocolErrorSchema),
};

type ClientHello = ProtocolMessageMap["client.hello"];
type PairingRequest = ProtocolMessageMap["pairing.request"];
type PairingCancel = ProtocolMessageMap["pairing.cancel"];
type PairingPending = ProtocolMessageMap["pairing.pending"];
type PairingApproved = ProtocolMessageMap["pairing.approved"];
type PairingDenied = ProtocolMessageMap["pairing.denied"];
type PairingExpired = ProtocolMessageMap["pairing.expired"];
type PairingCancelled = ProtocolMessageMap["pairing.cancelled"];
type PairingError = ProtocolMessageMap["pairing.error"];
type ServerHello = ProtocolMessageMap["server.hello"];
type Heartbeat = ProtocolMessageMap["heartbeat"];
type HeartbeatAck = ProtocolMessageMap["heartbeat.ack"];
type SourceDiscovered = ProtocolMessageMap["source.discovered"];
type SourceHealth = ProtocolMessageMap["source.health"];
type EvidenceEmit = ProtocolMessageMap["evidence.emit"];
type EventAck = ProtocolMessageMap["event.ack"];
type SourceCommand = ProtocolMessageMap["source.start"];
type SourceCommandAck = ProtocolMessageMap["source.command_ack"];
type UiEvent = ProtocolMessageMap["ui.event"];
type ProtocolError = ProtocolMessageMap["protocol.error"];

export interface ValidationResult<Type extends ProtocolMessageType> {
  valid: boolean;
  message?: ProtocolMessageMap[Type];
  errors: ErrorObject[];
}

export function validateProtocolMessage<Type extends ProtocolMessageType>(
  type: Type,
  value: unknown,
): ValidationResult<Type> {
  const validate = validators[type] as ValidateFunction<
    ProtocolMessageMap[Type]
  >;
  if (validate(value)) {
    if (
      type === "evidence.emit" &&
      (value as EvidenceEmit).interval_end_us <
        (value as EvidenceEmit).interval_start_us
    ) {
      return { valid: false, errors: [] };
    }
    return { valid: true, message: value, errors: [] };
  }
  return { valid: false, errors: validate.errors ?? [] };
}
