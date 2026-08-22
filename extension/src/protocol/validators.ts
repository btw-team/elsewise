import Ajv2020, {
  type ErrorObject,
  type ValidateFunction,
} from "ajv/dist/2020.js";
import addFormats from "ajv-formats";

import clientHelloSchema from "../../../protocol/schemas/client.hello.schema.json";
import eventAckSchema from "../../../protocol/schemas/event.ack.schema.json";
import protocolErrorSchema from "../../../protocol/schemas/protocol.error.schema.json";
import sourceStatusSchema from "../../../protocol/schemas/source.status.schema.json";
import uiEventSchema from "../../../protocol/schemas/ui.event.schema.json";
import utteranceFinalizeSchema from "../../../protocol/schemas/utterance.finalize.schema.json";
import utteranceUpsertSchema from "../../../protocol/schemas/utterance.upsert.schema.json";
import type { ProtocolMessageMap, ProtocolMessageType } from "./models";

const ajv = new Ajv2020({ allErrors: true, strict: true });
addFormats(ajv);

const validators: {
  [Type in ProtocolMessageType]: ValidateFunction<ProtocolMessageMap[Type]>;
} = {
  "client.hello": ajv.compile<ClientHello>(clientHelloSchema),
  "source.status": ajv.compile<SourceStatus>(sourceStatusSchema),
  "utterance.upsert": ajv.compile<UtteranceUpsert>(utteranceUpsertSchema),
  "utterance.finalize": ajv.compile<UtteranceFinalize>(utteranceFinalizeSchema),
  "event.ack": ajv.compile<EventAck>(eventAckSchema),
  "ui.event": ajv.compile<UiEvent>(uiEventSchema),
  "protocol.error": ajv.compile<ProtocolError>(protocolErrorSchema),
};

type ClientHello = ProtocolMessageMap["client.hello"];
type SourceStatus = ProtocolMessageMap["source.status"];
type UtteranceUpsert = ProtocolMessageMap["utterance.upsert"];
type UtteranceFinalize = ProtocolMessageMap["utterance.finalize"];
type EventAck = ProtocolMessageMap["event.ack"];
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
  if (validate(value)) return { valid: true, message: value, errors: [] };
  return { valid: false, errors: validate.errors ?? [] };
}
