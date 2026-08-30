use std::io::{self, Read};
use trendlab_core::{run_analysis_json, run_backtest_json};

fn main() {
    let mut args = std::env::args().skip(1);
    let cmd = args.next().unwrap_or_else(|| "analyze".into());
    let mut buf = String::new();
    io::stdin().read_to_string(&mut buf).expect("read stdin");
    let out = match cmd.as_str() {
        "analyze" => run_analysis_json(&buf),
        "backtest" => run_backtest_json(&buf),
        other => Err(format!("unknown cmd {other}")),
    };
    match out {
        Ok(s) => print!("{s}"),
        Err(e) => {
            eprintln!("{e}");
            std::process::exit(1);
        }
    }
}
