import React, { useEffect, useRef, useState } from 'react';
import { Terminal as XTerm } from 'xterm';
import { FitAddon } from 'xterm-addon-fit';
import { WebLinksAddon } from 'xterm-addon-web-links';
import { message, Button, Space } from 'antd';
import { DisconnectOutlined, FullscreenOutlined } from '@ant-design/icons';

// xterm 스타일 import (CDN 또는 로컬)
import 'xterm/css/xterm.css';

function Terminal({ sessionId, websocketUrl }) {
  const terminalRef = useRef(null);
  const xtermRef = useRef(null);
  const websocketRef = useRef(null);
  const fitAddonRef = useRef(null);
  const [isConnected, setIsConnected] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);

  useEffect(() => {
    if (!terminalRef.current || !sessionId) return;

    // XTerm 인스턴스 생성
    const terminal = new XTerm({
      cursorBlink: true,
      cursorStyle: 'block',
      fontFamily: 'Consolas, "Courier New", monospace',
      fontSize: 14,
      theme: {
        background: '#1e1e1e',
        foreground: '#d4d4d4',
        cursor: '#d4d4d4',
        selection: '#264f78',
        black: '#1e1e1e',
        red: '#f44747',
        green: '#608b4e',
        yellow: '#dcdcaa',
        blue: '#569cd6',
        magenta: '#c586c0',
        cyan: '#4fc1ff',
        white: '#d4d4d4',
        brightBlack: '#808080',
        brightRed: '#f44747',
        brightGreen: '#608b4e',
        brightYellow: '#dcdcaa',
        brightBlue: '#569cd6',
        brightMagenta: '#c586c0',
        brightCyan: '#4fc1ff',
        brightWhite: '#ffffff'
      },
      rows: 30,
      cols: 120,
      scrollback: 1000,
      tabStopWidth: 4,
    });

    // Addons 로드
    const fitAddon = new FitAddon();
    const webLinksAddon = new WebLinksAddon();
    
    terminal.loadAddon(fitAddon);
    terminal.loadAddon(webLinksAddon);
    
    xtermRef.current = terminal;
    fitAddonRef.current = fitAddon;

    // 터미널을 DOM에 연결
    terminal.open(terminalRef.current);
    fitAddon.fit();

    // WebSocket 연결
    connectWebSocket(terminal);

    // 리사이즈 이벤트 핸들러
    const handleResize = () => {
      setTimeout(() => {
        if (fitAddon && terminal) {
          fitAddon.fit();
        }
      }, 100);
    };

    window.addEventListener('resize', handleResize);

    // 정리 함수
    return () => {
      window.removeEventListener('resize', handleResize);

      // 페이지 종료 시 백엔드 세션도 정리
      if (sessionId) {
        fetch(`/api/terminal/sessions/${sessionId}`, {
          method: 'DELETE',
          keepalive: true  // 페이지 종료 시에도 요청 완료 보장
        }).catch(err => console.warn('세션 정리 실패:', err));
      }

      if (websocketRef.current) {
        websocketRef.current.close();
      }

      if (terminal) {
        terminal.dispose();
      }
    };
  }, [sessionId]);

  const connectWebSocket = (terminal) => {
    try {
      // WebSocket URL 구성 (HTTP를 WS로 변경)
      const wsUrl = websocketUrl.replace('http://', 'ws://').replace('https://', 'wss://');
      const ws = new WebSocket(wsUrl);
      
      websocketRef.current = ws;

      ws.onopen = () => {
        setIsConnected(true);
        terminal.write('\r\n🔗 터미널에 연결되었습니다...\r\n');
        message.success('터미널 연결 성공');
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          
          if (data.type === 'output') {
            // 서버에서 직접 텍스트로 전송하므로 그대로 사용
            terminal.write(data.data);
          }
        } catch (error) {
          // JSON이 아닌 경우 그대로 출력
          terminal.write(event.data);
        }
      };

      ws.onclose = (event) => {
        setIsConnected(false);
        terminal.write(`\r\n🔌 터미널 연결이 종료되었습니다 (코드: ${event.code})\r\n`);
        message.warning('터미널 연결이 종료되었습니다');
      };

      ws.onerror = (error) => {
        setIsConnected(false);
        terminal.write('\r\n❌ 터미널 연결 오류가 발생했습니다\r\n');
        message.error('터미널 연결 오류: ' + error.message);
      };

      // 터미널 입력 처리
      terminal.onData((data) => {
        if (ws.readyState === WebSocket.OPEN) {
          const message = JSON.stringify({
            type: 'input',
            data: data
          });
          ws.send(message);
        }
      });

    } catch (error) {
      message.error('WebSocket 연결 실패: ' + error.message);
    }
  };

  const handleDisconnect = async () => {
    try {
      // 백엔드 API를 통해 세션 종료 (AWS SSM 세션 포함)
      const response = await fetch(`/api/terminal/sessions/${sessionId}`, {
        method: 'DELETE'
      });

      if (response.ok) {
        message.success('터미널 세션이 정상적으로 종료되었습니다');
      } else {
        message.warning('세션 종료 중 문제가 발생했습니다');
      }
    } catch (error) {
      console.error('세션 종료 오류:', error);
      message.error('세션 종료 실패');
    }

    // WebSocket 연결 종료
    if (websocketRef.current) {
      websocketRef.current.close();
    }

    setIsConnected(false);
  };

  const handleFullscreen = () => {
    if (!isFullscreen) {
      if (terminalRef.current?.requestFullscreen) {
        terminalRef.current.requestFullscreen();
        setIsFullscreen(true);
      }
    } else {
      if (document.exitFullscreen) {
        document.exitFullscreen();
        setIsFullscreen(false);
      }
    }
  };

  const handleClear = () => {
    if (xtermRef.current) {
      xtermRef.current.clear();
    }
  };

  const handleFit = () => {
    if (fitAddonRef.current && xtermRef.current) {
      fitAddonRef.current.fit();
    }
  };

  return (
    <div>
      {/* 터미널 컨트롤 */}
      <div style={{ 
        marginBottom: '8px', 
        display: 'flex', 
        justifyContent: 'space-between',
        alignItems: 'center',
        padding: '8px',
        background: '#f5f5f5',
        borderRadius: '4px'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <div style={{ 
            width: '8px', 
            height: '8px', 
            borderRadius: '50%', 
            backgroundColor: isConnected ? '#52c41a' : '#ff4d4f' 
          }} />
          <span style={{ fontSize: '12px', color: '#666' }}>
            {isConnected ? '연결됨' : '연결 끊김'} | 세션 ID: {sessionId}
          </span>
        </div>
        
        <Space>
          <Button size="small" onClick={handleClear}>
            지우기
          </Button>
          <Button size="small" onClick={handleFit}>
            크기 조정
          </Button>
          <Button 
            size="small" 
            icon={<FullscreenOutlined />} 
            onClick={handleFullscreen}
          >
            전체화면
          </Button>
          <Button 
            size="small" 
            danger
            icon={<DisconnectOutlined />} 
            onClick={handleDisconnect}
          >
            연결 끊기
          </Button>
        </Space>
      </div>

      {/* 터미널 */}
      <div 
        ref={terminalRef}
        style={{
          border: '1px solid #d9d9d9',
          borderRadius: '4px',
          backgroundColor: '#1e1e1e',
          minHeight: '400px'
        }}
      />

      {/* 도움말 */}
      <div style={{ 
        marginTop: '8px', 
        fontSize: '12px', 
        color: '#666',
        textAlign: 'center'
      }}>
        💡 팁: Ctrl+C로 명령 중단, Ctrl+D로 세션 종료, Ctrl+L로 화면 지우기
      </div>
    </div>
  );
}

export default Terminal;