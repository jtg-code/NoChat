use serde_json::{json, Map, Value};
use std::collections::HashMap;
use std::io::{self, BufRead, BufReader, Write};
use std::net::{SocketAddr, TcpListener, TcpStream};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;

const HOST: &str = "127.0.0.1";
const PORT: u16 = 5555;

struct ClientEntry {
    id: u64,
    stream: Arc<Mutex<TcpStream>>,
    show_online_status: bool,
}

type ClientMap = Arc<Mutex<HashMap<String, ClientEntry>>>;

static NEXT_CLIENT_ID: AtomicU64 = AtomicU64::new(1);

fn send_json(stream: &Mutex<TcpStream>, payload: &Value) -> io::Result<()> {
    let mut data = serde_json::to_vec(payload)
        .map_err(|e| io::Error::new(io::ErrorKind::InvalidData, e))?;
    data.push(b'\n');

    let mut guard = stream
        .lock()
        .map_err(|_| io::Error::new(io::ErrorKind::Other, "stream mutex poisoned"))?;
    guard.write_all(&data)?;
    guard.flush()
}

fn send_error(stream: &Mutex<TcpStream>, message: &str) {
    let payload = json!({
        "type": "error",
        "message": message,
    });
    let _ = send_json(stream, &payload);
}

fn broadcast_presence(
    clients: &ClientMap,
    exclude_client_id: Option<u64>,
    pub_key: &str,
    is_online: bool,
) {
    let targets: Vec<Arc<Mutex<TcpStream>>> = {
        let map = clients.lock().unwrap_or_else(|e| e.into_inner());
        map.values()
            .filter(|entry| Some(entry.id) != exclude_client_id)
            .map(|entry| Arc::clone(&entry.stream))
            .collect()
    };

    if targets.is_empty() {
        return;
    }

    let mut statuses = Map::new();
    statuses.insert(pub_key.to_string(), Value::Bool(is_online));
    let payload = json!({
        "type": "presence",
        "statuses": statuses,
    });

    for target in targets {
        let _ = send_json(&target, &payload);
    }
}

fn handle_client(stream: TcpStream, addr: SocketAddr, clients: ClientMap) {
    let client_id = NEXT_CLIENT_ID.fetch_add(1, Ordering::Relaxed);
    let read_stream = match stream.try_clone() {
        Ok(s) => s,
        Err(_) => return,
    };
    let write_stream = Arc::new(Mutex::new(stream));
    let mut reader = BufReader::new(read_stream);
    let mut registered_pub_key: Option<String> = None;
    let mut line = String::new();

    loop {
        line.clear();
        match reader.read_line(&mut line) {
            Ok(0) => break, // EOF
            Ok(_) => {}
            Err(_) => break,
        }

        let trimmed = line.trim();
        if trimmed.is_empty() {
            continue;
        }

        let msg: Value = match serde_json::from_str(trimmed) {
            Ok(v) => v,
            Err(_) => {
                send_error(&write_stream, "Ungültiges JSON-Format.");
                continue;
            }
        };

        let msg_type = msg.get("type").and_then(Value::as_str);

        match msg_type {
            Some("register") => {
                let pub_key = msg
                    .get("public_key")
                    .and_then(Value::as_str)
                    .map(str::trim)
                    .unwrap_or("");

                if pub_key.is_empty() {
                    send_error(&write_stream, "Kein Public Key angegeben.");
                    continue;
                }

                let show_online_status = msg
                    .get("show_online_status")
                    .and_then(Value::as_bool)
                    .unwrap_or(true);

                let pub_key_owned = pub_key.to_string();
                let mut removed_old_key: Option<String> = None;
                {
                    let mut map = clients.lock().unwrap_or_else(|e| e.into_inner());
                    if let Some(old_key) = registered_pub_key.as_ref() {
                        if old_key != &pub_key_owned {
                            if let Some(entry) = map.get(old_key) {
                                if entry.id == client_id {
                                    map.remove(old_key);
                                    removed_old_key = Some(old_key.clone());
                                }
                            }
                        }
                    }
                    map.insert(
                        pub_key_owned.clone(),
                        ClientEntry {
                            id: client_id,
                            stream: Arc::clone(&write_stream),
                            show_online_status,
                        },
                    );
                }
                registered_pub_key = Some(pub_key_owned.clone());
                println!(
                    "[+] Client registriert ({}:{}): {} (Online-Status: {})",
                    addr.ip(),
                    addr.port(),
                    pub_key_owned,
                    show_online_status
                );

                if let Some(old_key) = removed_old_key {
                    broadcast_presence(&clients, Some(client_id), &old_key, false);
                }
                broadcast_presence(&clients, Some(client_id), &pub_key_owned, show_online_status);
            }
            Some("presence_update") => {
                let Some(pub_key) = registered_pub_key.as_ref() else {
                    send_error(&write_stream, "Client ist nicht registriert.");
                    continue;
                };

                let Some(show_online_status) =
                    msg.get("show_online_status").and_then(Value::as_bool)
                else {
                    send_error(
                        &write_stream,
                        "Ungültiges oder fehlendes Feld 'show_online_status'.",
                    );
                    continue;
                };

                let updated = {
                    let mut map = clients.lock().unwrap_or_else(|e| e.into_inner());
                    if let Some(entry) = map.get_mut(pub_key) {
                        if entry.id == client_id {
                            entry.show_online_status = show_online_status;
                            true
                        } else {
                            false
                        }
                    } else {
                        false
                    }
                };

                if updated {
                    broadcast_presence(&clients, Some(client_id), pub_key, show_online_status);
                }
            }
            Some("presence_query") => {
                let Some(keys_val) = msg.get("public_keys").and_then(Value::as_array) else {
                    send_error(
                        &write_stream,
                        "Ungültiges oder fehlendes Feld 'public_keys'.",
                    );
                    continue;
                };

                let mut statuses = Map::new();
                {
                    let map = clients.lock().unwrap_or_else(|e| e.into_inner());
                    for key_val in keys_val {
                        if let Some(raw_key) = key_val.as_str() {
                            let key = raw_key.trim();
                            if key.is_empty() {
                                continue;
                            }
                            let is_online = map
                                .get(key)
                                .map(|entry| entry.show_online_status)
                                .unwrap_or(false);
                            statuses.insert(key.to_string(), Value::Bool(is_online));
                        }
                    }
                }

                let response = json!({
                    "type": "presence",
                    "statuses": statuses,
                });
                let _ = send_json(&write_stream, &response);
            }
            Some("message") => {
                let recipient_key = msg
                    .get("recipient_public_key")
                    .and_then(Value::as_str)
                    .map(str::trim)
                    .unwrap_or("");

                let target_stream = {
                    let map = clients.lock().unwrap_or_else(|e| e.into_inner());
                    map.get(recipient_key).map(|entry| Arc::clone(&entry.stream))
                };

                match target_stream {
                    None => {
                        send_error(
                            &write_stream,
                            "Empfänger ist nicht verbunden oder Public Key unbekannt.",
                        );
                    }
                    Some(target) => {
                        if send_json(&target, &msg).is_err() {
                            send_error(&write_stream, "Zustellung an Empfänger fehlgeschlagen.");
                        }
                    }
                }
            }
            Some(other) => {
                send_error(&write_stream, &format!("Unbekannter Paket-Typ: {}", other));
            }
            None => {
                send_error(&write_stream, "Fehlendes Feld 'type'.");
            }
        }
    }

    if let Some(pub_key) = registered_pub_key {
        let removed = {
            let mut map = clients.lock().unwrap_or_else(|e| e.into_inner());
            if let Some(entry) = map.get(&pub_key) {
                if entry.id == client_id {
                    map.remove(&pub_key);
                    true
                } else {
                    false
                }
            } else {
                false
            }
        };

        if removed {
            broadcast_presence(&clients, Some(client_id), &pub_key, false);
        }
        println!("[-] Client getrennt: {}", pub_key);
    }
}

fn main() -> io::Result<()> {
    let port: u16 = std::env::var("NOCHAT_PORT")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(PORT);
    let bind_addr = format!("{}:{}", HOST, port);
    let listener = TcpListener::bind(&bind_addr)?;
    println!("E2EE-Relay-Server läuft auf {} ...", bind_addr);

    let clients: ClientMap = Arc::new(Mutex::new(HashMap::new()));

    for incoming in listener.incoming() {
        match incoming {
            Ok(stream) => {
                let addr = match stream.peer_addr() {
                    Ok(a) => a,
                    Err(_) => continue,
                };
                let clients_ref = Arc::clone(&clients);
                thread::spawn(move || {
                    handle_client(stream, addr, clients_ref);
                });
            }
            Err(err) => {
                eprintln!("[!] Accept-Fehler: {}", err);
            }
        }
    }

    Ok(())
}
