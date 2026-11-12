//! Cliente HTTP mínimo para o servidor local (127.0.0.1). O servidor Python é
//! HTTP/1.0 e fecha a conexão a cada resposta, então basta ler até o fim.
//! Sem dependências: compila rápido e não traz TLS nem resolvedor de DNS.

use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use serde_json::Value;

#[derive(Debug, Clone)]
pub struct Resposta {
    pub status: u16,
    pub cabecalhos: Vec<(String, String)>,
    pub corpo: Vec<u8>,
}

impl Resposta {
    pub fn json(&self) -> Option<Value> {
        serde_json::from_slice(&self.corpo).ok()
    }
    pub fn cabecalho(&self, nome: &str) -> Option<&str> {
        self.cabecalhos
            .iter()
            .find(|(k, _)| k.eq_ignore_ascii_case(nome))
            .map(|(_, v)| v.as_str())
    }
    pub fn ok(&self) -> bool {
        (200..300).contains(&self.status)
    }
}

/// Servidor + cookie da sessão dos pais (depois de um PIN correto).
#[derive(Clone)]
pub struct Api {
    pub porta: u16,
    cookie: Arc<Mutex<Option<String>>>,
}

impl Api {
    pub fn new(porta: u16) -> Self {
        Self { porta, cookie: Arc::new(Mutex::new(None)) }
    }

    pub fn base(&self) -> String {
        format!("http://127.0.0.1:{}", self.porta)
    }

    pub fn get(&self, caminho: &str) -> std::io::Result<Resposta> {
        self.requisicao("GET", caminho, None, Duration::from_secs(10))
    }

    pub fn get_json(&self, caminho: &str) -> Option<Value> {
        let r = self.get(caminho).ok()?;
        if !r.ok() {
            return None;
        }
        r.json()
    }

    pub fn post(&self, caminho: &str, corpo: Option<&Value>) -> std::io::Result<Resposta> {
        let texto = corpo.map(|v| v.to_string());
        self.requisicao("POST", caminho, texto.as_deref(), Duration::from_secs(30))
    }

    pub fn esquecer_sessao(&self) {
        *self.cookie.lock().unwrap() = None;
    }

    fn requisicao(
        &self,
        metodo: &str,
        caminho: &str,
        corpo: Option<&str>,
        limite: Duration,
    ) -> std::io::Result<Resposta> {
        let endereco = SocketAddr::from(([127, 0, 0, 1], self.porta));
        let mut s = TcpStream::connect_timeout(&endereco, Duration::from_secs(3))?;
        s.set_read_timeout(Some(limite))?;
        s.set_write_timeout(Some(Duration::from_secs(5)))?;
        let mut pedido = format!(
            "{metodo} {caminho} HTTP/1.1\r\nHost: 127.0.0.1:{}\r\nConnection: close\r\nAccept: application/json\r\n",
            self.porta
        );
        if let Some(c) = self.cookie.lock().unwrap().as_ref() {
            pedido.push_str(&format!("Cookie: {c}\r\n"));
        }
        let corpo = corpo.unwrap_or(if metodo == "POST" { "{}" } else { "" });
        if metodo == "POST" {
            pedido.push_str("Content-Type: application/json\r\n");
            pedido.push_str(&format!("Content-Length: {}\r\n", corpo.len()));
        }
        pedido.push_str("\r\n");
        pedido.push_str(corpo);
        s.write_all(pedido.as_bytes())?;
        let mut bruto = Vec::with_capacity(8192);
        s.read_to_end(&mut bruto)?;
        let resposta = interpretar(&bruto).ok_or_else(|| {
            std::io::Error::new(std::io::ErrorKind::InvalidData, "resposta HTTP inválida")
        })?;
        if let Some(c) = resposta.cabecalho("Set-Cookie") {
            // "nome=valor; Path=/; HttpOnly..." → só "nome=valor"
            let par = c.split(';').next().unwrap_or("").trim().to_string();
            if !par.is_empty() {
                *self.cookie.lock().unwrap() = Some(par);
            }
        }
        Ok(resposta)
    }
}

fn interpretar(bruto: &[u8]) -> Option<Resposta> {
    let fim = bruto.windows(4).position(|w| w == b"\r\n\r\n")?;
    let cabeca = std::str::from_utf8(&bruto[..fim]).ok()?;
    let mut linhas = cabeca.split("\r\n");
    let status: u16 = linhas.next()?.split_whitespace().nth(1)?.parse().ok()?;
    let cabecalhos: Vec<(String, String)> = linhas
        .filter_map(|l| l.split_once(':'))
        .map(|(k, v)| (k.trim().to_string(), v.trim().to_string()))
        .collect();
    let mut corpo = bruto[fim + 4..].to_vec();
    let chunked = cabecalhos.iter().any(|(k, v)| {
        k.eq_ignore_ascii_case("Transfer-Encoding") && v.eq_ignore_ascii_case("chunked")
    });
    if chunked {
        corpo = dechunk(&corpo)?;
    }
    Some(Resposta { status, cabecalhos, corpo })
}

fn dechunk(mut dados: &[u8]) -> Option<Vec<u8>> {
    let mut saida = Vec::new();
    loop {
        let fim = dados.windows(2).position(|w| w == b"\r\n")?;
        let tamanho = usize::from_str_radix(
            std::str::from_utf8(&dados[..fim]).ok()?.split(';').next()?.trim(),
            16,
        )
        .ok()?;
        dados = &dados[fim + 2..];
        if tamanho == 0 {
            return Some(saida);
        }
        saida.extend_from_slice(dados.get(..tamanho)?);
        dados = dados.get(tamanho + 2..)?;
    }
}

/// Codifica um componente de URL (para ids de tiles já validados basta pouco).
pub fn codificar(texto: &str) -> String {
    let mut s = String::new();
    for b in texto.bytes() {
        match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => s.push(b as char),
            _ => s.push_str(&format!("%{b:02X}")),
        }
    }
    s
}

#[cfg(test)]
mod testes {
    use super::*;

    #[test]
    fn interpreta_resposta_simples() {
        let r = interpretar(b"HTTP/1.0 302 Found\r\nLocation: /browser.html?x=1\r\nSet-Cookie: s=abc; Path=/\r\n\r\n").unwrap();
        assert_eq!(r.status, 302);
        assert_eq!(r.cabecalho("location"), Some("/browser.html?x=1"));
        assert!(r.corpo.is_empty());
    }

    #[test]
    fn interpreta_chunked() {
        let r = interpretar(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n3\r\nabc\r\n2\r\nde\r\n0\r\n\r\n").unwrap();
        assert_eq!(r.corpo, b"abcde");
    }

    #[test]
    fn codifica_url() {
        assert_eq!(codificar("a b/ç"), "a%20b%2F%C3%A7");
    }
}
