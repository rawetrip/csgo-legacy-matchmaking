"""Build the [csgc] party.js using the OFFICIAL event paths.

Replaces yesterday's generator, which had grown unmaintainable (duplicated try
blocks, escaping fights) and produced broken JS.

Two things this does differently from all previous attempts:

  * trigger: dispatch the "ServerReserved" event, which party.js already registers
    a handler for via $.RegisterForUnhandledEvent. That is exactly how the engine
    was supposed to raise it. (Previously we called PartyMenu.ShowMatchAcceptPopUp
    directly, bypassing the event system.)
  * close: dispatch "PanoramaComponent_Lobby_ReadyUpForMatch" with shouldShow=false,
    which is the popup's own teardown branch.

usage: py make_party.py <pristine party.js> <out.js>
"""
import sys

TAB = chr(9)
NL = chr(13) + chr(10)
def L(n, s):
    return TAB * n + s

src = open(sys.argv[1], encoding="utf-8", newline="").read()

# ---------------------------------------------------------------- watcher block
w = []
A = w.append
A(L(1, "PartyMenu.Init();"))
A("")
A(L(1, '$.Msg( "[csgc] party.js LOADED v7" );'))
A(L(1, "var _csgcLast = null;"))
A(L(1, "var _csgcShown = false;"))
A(L(1, "var _csgcClosed = false;"))
A("")
A(L(1, "// close via the popup's own handler -- that is the official teardown path"))
A(L(1, "var _closePopup = function()"))
A(L(1, "{"))
A(L(2, 'try { $.DispatchEvent( "PanoramaComponent_Lobby_ReadyUpForMatch", false, 0, 0 ); } catch ( e ) { }'))
A(L(2, "// NB: do NOT play popup_accept_match_confirmed here. In the '@' path the"))
A(L(2, "// official _OnNqmmAutoReadyUp already plays it -- playing it here as well is"))
A(L(2, "// exactly the 'lets roll twice' bug (which real CS2/CS:GO also have)."))
A(L(1, "};"))
A("")
A(L(1, "var _csgcWatch = function()"))
A(L(1, "{"))
A(L(2, 'var status = "", mmq = "";'))
A(L(2, 'try { status = String( LobbyAPI.GetMatchmakingStatusString() ); } catch ( e ) { status = ""; }'))
A(L(2, "try"))
A(L(2, "{"))
A(L(3, "var s = LobbyAPI.GetSessionSettings();"))
A(L(3, "if ( s && s.game ) mmq = String( s.game.mmqueue );"))
A(L(2, "}"))
A(L(2, 'catch ( e ) { mmq = ""; }'))
A("")
A(L(2, "var conn = false;"))
A(L(2, "try { conn = !!GameStateAPI.IsPlayerConnected(); } catch ( e ) { conn = false; }"))
A("")
A(L(2, "// State-driven close (no timer guessing): fires the moment the client"))
A(L(2, "// actually connects, i.e. as the loading screen comes up -- the same"))
A(L(2, "// moment the official popup disappears. Only after WE raised it."))
A(L(2, "try"))
A(L(2, "{"))
A(L(3, "if ( _csgcShown && ( GameStateAPI.IsLocalPlayerPlayingMatch() || conn ) )"))
A(L(3, "{"))
A(L(4, "if ( !_csgcClosed )"))
A(L(4, "{"))
A(L(5, "_csgcClosed = true;"))
A(L(5, '$.Msg( "[csgc] connected (conn=" + conn + ") -- closing popup" );'))
A(L(5, "_closePopup();"))
A(L(4, "}"))
A(L(3, "}"))
A(L(3, "else"))
A(L(3, "{"))
A(L(4, "_csgcClosed = false;"))
A(L(3, "}"))
A(L(2, "}"))
A(L(2, "catch ( e ) { }"))
A("")
A(L(2, 'var sig = status + "|" + mmq;'))
A(L(2, "if ( sig !== _csgcLast )"))
A(L(2, "{"))
A(L(3, '$.Msg( "[csgc] state: mmstatus=\'" + status + "\' mmqueue=\'" + mmq + "\'" );'))
A(L(3, "_csgcLast = sig;"))
A(L(3, 'var reserved = ( status.indexOf( "reserved" ) >= 0 ) || ( mmq === "reserved" );'))
A(L(3, "if ( reserved && !_csgcShown )"))
A(L(3, "{"))
A(L(4, "_csgcShown = true;"))
A(L(4, '$.Msg( "[csgc] RESERVED -- raising ServerReserved" );'))
A(L(4, "// the official trigger: party.js registered this event itself"))
A(L(4, "// use the real map the client is reserved for, not a hardcoded one"))
A(L(4, "var _map = \"de_dust2\";"))
A(L(4, "try { var _g = LobbyAPI.GetSessionSettings(); if ( _g && _g.game && _g.game.map ) _map = String( _g.game.map ); } catch ( e ) { }"))
A(L(4, "// '@' prefix = the official 'announcement only / auto ready-up' mode: the popup"))
A(L(4, "// takes its casual look, suppresses the beep, and 1.9s later calls"))
A(L(4, "// _OnNqmmAutoReadyUp -- which plays the confirmed sound, does"))
A(L(4, "// LobbyAPI.SetLocalPlayerReady('deferred') and closes via the official path."))
A(L(4, 'try { $.DispatchEvent( "ServerReserved", "@" + _map ); $.Msg( "[csgc] ServerReserved raised for @" + _map ); }'))
A(L(4, 'catch ( e ) { $.Msg( "[csgc] raise threw: " + e ); }'))
A(L(4, "// the engine normally plays this when it raises ServerReserved itself;"))
A(L(4, "// since WE raise it, nobody else will -- play the match-ready sound here."))
A(L(4, 'try { $.DispatchEvent( "PlaySoundEffect", "popup_accept_match_found", "MOUSE" ); } catch ( e ) { }'))
A(L(4, "// Safety net only now: in the '@' path the popup closes itself at 1.9s via"))
A(L(4, "// the official _OnNqmmAutoReadyUp. Keep this well past csgc's connect."))
A(L(4, "$.Schedule( 12.0, function()"))
A(L(4, "{"))
A(L(5, '$.Msg( "[csgc] timed close" );'))
A(L(5, "_closePopup();"))
A(L(4, "} );"))
A(L(3, "}"))
A(L(3, "else if ( !reserved )"))
A(L(3, "{"))
A(L(4, "_csgcShown = false;"))
A(L(3, "}"))
A(L(2, "}"))
A(L(2, "// poll fast: the popup's t=0 is our first poll after mmqueue flips to"))
A(L(2, "// 'reserved', and the close timer below is measured from there."))
A(L(2, "$.Schedule( 0.2, _csgcWatch );"))
A(L(1, "};"))
A(L(1, "// THE close that matters: fires the instant a level starts loading, i.e."))
A(L(1, "// exactly when the loading screen appears. Polling GameStateAPI never sees"))
A(L(1, "// this moment (IsPlayerConnected stays false while '正在连接至服务器...')."))
A(L(1, "$.RegisterForUnhandledEvent( 'GameState_LevelInitPreEntity', function()"))
A(L(1, "{"))
A(L(2, 'if ( _csgcShown )'))
A(L(2, "{"))
A(L(3, "_csgcClosed = true;"))
A(L(3, '$.Msg( "[csgc] level init -- closing popup" );'))
A(L(3, "_closePopup();"))
A(L(2, "}"))
A(L(1, "} );"))
A("")
A(L(1, "$.Schedule( 1.0, _csgcWatch );"))

ANCHOR = L(1, "PartyMenu.Init();")
assert src.count(ANCHOR) == 1, "PartyMenu.Init anchor not found"
src = src.replace(ANCHOR, NL.join(w))

assert "party.js LOADED v7" in src
assert "ServerReserved raised" in src
open(sys.argv[2], "w", encoding="utf-8", newline="").write(src)
print("built: v7 (official serverreserved trigger + readyup close)")
