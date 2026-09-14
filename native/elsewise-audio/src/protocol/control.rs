use std::io::{self, Read, Write};

use serde_json::Value;

use super::frame::PROTOCOL_VERSION;

pub const MAX_CONTROL_MESSAGE_BYTES: usize = 64 * 1024;

pub fn read_control_frame(reader: &mut impl Read) -> io::Result<Value> {
    let mut length = [0_u8; 4];
    reader.read_exact(&mut length)?;
    let payload_bytes = u32::from_le_bytes(length) as usize;
    if payload_bytes == 0 || payload_bytes > MAX_CONTROL_MESSAGE_BYTES {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "control message exceeds the protocol bound",
        ));
    }

    let mut payload = vec![0_u8; payload_bytes];
    reader.read_exact(&mut payload)?;
    let message: Value = serde_json::from_slice(&payload)
        .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))?;
    validate_control_message(&message)?;
    Ok(message)
}

pub fn write_control_frame(writer: &mut impl Write, message: &Value) -> io::Result<()> {
    validate_control_message(message)?;
    let payload = serde_json::to_vec(message)
        .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))?;
    if payload.is_empty() || payload.len() > MAX_CONTROL_MESSAGE_BYTES {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "control message exceeds the protocol bound",
        ));
    }
    writer.write_all(&(payload.len() as u32).to_le_bytes())?;
    writer.write_all(&payload)?;
    writer.flush()
}

fn validate_control_message(message: &Value) -> io::Result<()> {
    let object = message.as_object().ok_or_else(|| {
        io::Error::new(
            io::ErrorKind::InvalidData,
            "control message must be an object",
        )
    })?;
    if object.get("protocol_version").and_then(Value::as_u64) != Some(u64::from(PROTOCOL_VERSION)) {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "unsupported audio protocol version",
        ));
    }
    let message_type = object
        .get("type")
        .and_then(Value::as_str)
        .unwrap_or_default();
    if message_type.is_empty() || message_type.len() > 64 {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "control message type is invalid",
        ));
    }
    if let Some(request_id) = object.get("request_id") {
        let request_id = request_id.as_str().unwrap_or_default();
        if request_id.is_empty() || request_id.len() > 128 {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "control request_id is invalid",
            ));
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn round_trips_a_bounded_message() {
        let message = json!({
            "type": "daemon.hello",
            "protocol_version": PROTOCOL_VERSION,
            "request_id": "request-1"
        });
        let mut encoded = Vec::new();
        write_control_frame(&mut encoded, &message).unwrap();
        assert_eq!(
            read_control_frame(&mut encoded.as_slice()).unwrap(),
            message
        );
    }

    #[test]
    fn rejects_an_oversized_length_before_allocating_payload() {
        let encoded = ((MAX_CONTROL_MESSAGE_BYTES + 1) as u32).to_le_bytes();
        let error = read_control_frame(&mut encoded.as_slice()).unwrap_err();
        assert_eq!(error.kind(), io::ErrorKind::InvalidData);
    }
}
