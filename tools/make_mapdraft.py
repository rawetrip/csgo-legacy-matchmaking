#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从**你自己**游戏里的 panorama/scripts/mapdraft.js 生成「BP 自动点票」补丁版。

    usage: py make_mapdraft.py <pristine mapdraft.js> <out.js> [mode] [target_map]

        mode        opp_random（默认）= 只在**对方**轮次随机代投，我方轮次交给人点
                    target          = 轮到我方时把非目标图全 ban 掉，自动定到 target_map
        target_map  target 模式下要保住的图，默认 de_mirage

为什么要自己生成
----------------
这个补丁改的是 **Valve 的** `csgo/panorama/scripts/mapdraft.js`。Valve 在
2018-06-21 曾为「从 `code.pbin` 反编译出来的 Panorama JS 与 layout」发过 DMCA
通知（https://github.com/github/dmca/blob/master/2018/2018-06-21-Valve.md），
所以本仓库**只提供生成器，不分发改好的成品**。请从你自己的 `code.pbin` 取出原始件：

    py tools/pbin_tool.py get panorama/scripts/mapdraft.js mapdraft_orig.js

先核对原始件（对不上就是原始件不对，别继续）：

    **24481** 字节 · CRLF 行尾 · 无 BOM

生成（游戏必须关着）：

    py tools/make_mapdraft.py mapdraft_orig.js mapdraft_patched.js
    py tools/pbin_tool.py put panorama/scripts/mapdraft.js mapdraft_patched.js
    py tools/pbin_tool.py get panorama/scripts/mapdraft.js readback.js
    cmp readback.js mapdraft_patched.js && echo OK

默认参数下产物为 **30574** 字节 · 纯 LF · 无 BOM。

这个脚本把历史上的 v10 → v11 → v12 三步合成**一次确定性变换**
-------------------------------------------------------------
  · 调用点注入官方 `_Update` 的**最开头**。它前面有好几个提前 `return`
    （`if ( sGameUiState !== ... ) return;`），插在末尾的那些 return 一发生就永远到不了。
  · 实现块必须放在 **MapDraft 主闭包内部**。放到闭包外是 `ReferenceError`，
    而 Panorama 里**没有 `window`**，于是整个文件执行中断 —— 连"已装载"日志都打不出来，
    看起来像补丁没被加载。v1~v9 就是被这里的空 `catch` 静默吞掉了两百多次异常。
  · `voteid` 必须是**字符串**（官方代码全是 `.toString()`）；`GetIngameTeamToActNow()`
    返回的是字符串，跟数字 `myTeam` 直接比会恒不相等，要先 `Number()` 再比。
"""

import sys

# ── 锚点（都在官方原始件里唯一）───────────────────────────────────────────
ANCHOR_REG = "\t$.RegisterForUnhandledEvent( 'PanoramaComponent_IngameDraft_DraftUpdate', _Update );\n"

ANCHOR_UPD = (
    "\tfunction _Update()\n"
    "\t{\n"
    "\t\tlet sGameUiState = GameStateAPI.GetCSGOGameUIStateName();\n"
)

UPD_HOOK = (
    "\tfunction _Update()\n"
    "\t{\n"
    "\t\t// [csgc] BP 自动投票 —— 在函数**最开头**，前面的 return 拦不住。\n"
    "\t\t// catch 里打日志，不再静默吞掉（v1~v9 就是被这里吞了两百多次）。\n"
    "\t\ttry { __csgcAutoVote(); } catch ( e ) { $.Msg( '[csgc] BP 注入异常: ' + e ); }\n\n"
    "\t\tlet sGameUiState = GameStateAPI.GetCSGOGameUIStateName();\n"
)

# ── 闭包内前言（原样来自 v12）─────────────────────────────────────────────
PREAMBLE = """\
	// ═══════════════════════════════════════════════════════════════════════
	// [csgc] BP 自动投票 —— 与 _Update 处于**同一个闭包**，不存在作用域问题。
	//   目标：把所有非 de_mirage 的图 ban 掉；阵营随机。
	//   去重：靠 (phase + 图列表 + 各图状态) 的签名，状态一变才再投一次。
	// ═══════════════════════════════════════════════════════════════════════
	var __csgcTarget    = 'de_mirage';
	var __csgcLastSig   = null;
	var __csgcLastVote  = '';
	var __csgcLogCount  = 0;

	"""

# ── 实现块（原样来自 v12）─────────────────────────────────────────────────
V12_IMPL = """\
	// ── 模式 ─────────────────────────────────────────────────────────────
	//   'opp_random' = 对方轮次由我们**随机**代投；我方轮次什么都不做，交给人点  ← 当前
	//   'target'     = 轮到我方时把非目标图全 ban 掉，自动定到 __csgcTarget（v11 的行为）
	var __csgcMode = 'opp_random';

	function __csgcVote( phase, voteid )
	{
		var slot = 0;
		for ( var i = 0; i < 4; i++ )
		{
			var v = null;
			try { v = MatchDraftAPI.GetIngameMyVoteInSlot( i ); } catch ( e ) { v = null; }
			if ( !v || v === 'empty' ) { slot = i; break; }
		}
		try
		{
			MatchDraftAPI.ActionIngameCastMyVote( phase, slot, voteid );
			return true;
		}
		catch ( e )
		{
			$.Msg( '[csgc] BP投票抛异常 phase=' + phase + ' voteid=' + voteid + ' : ' + e );
			return false;
		}
	}

	// 随机代投一票。phase 1/5 的 voteid 是队伍号（T=2 / CT=3），phase 2/3/4 是图 id。
	// 返回是否为"真正投了一次"。
	function __csgcVoteRandom( phase, list, states )
	{
		// phase 1 = 抢「先 ban」（voteid 是队伍号）；phase 5 = 选初始阵营
		if ( phase === 1 || phase === 5 )
		{
			var team = ( Math.random() < 0.5 ) ? '2' : '3';
			$.Msg( '[csgc] BP代投(对方随机) phase=' + phase + ' voteid=' + team );
			return __csgcVote( phase, team );
		}

		// phase 2/3/4 = ban 图：在还没被 veto/pick 的图里随机挑一张
		var cand = [];
		for ( var j = 0; j < list.length; j++ )
		{
			var id = list[j];
			if ( !id ) continue;
			var s2 = '';
			try { s2 = '' + MatchDraftAPI.GetIngameMapIdState( id ); } catch ( e ) { continue; }
			if ( s2 === 'veto' || s2 === 'pick' ) continue;
			cand.push( id );
		}
		if ( !cand.length ) return false;
		var pick = cand[ Math.floor( Math.random() * cand.length ) ];
		$.Msg( '[csgc] BP代投(对方随机) phase=' + phase + ' voteid=' + pick + ' 候选=' + cand.join( ',' ) );
		return __csgcVote( phase, pick );
	}

	// target 模式：只在我方轮次干活，ban 掉除目标图以外的第一张
	function __csgcVoteTarget( phase, list, states, myTeam, turnN, ids )
	{
		if ( turnN && turnN !== myTeam ) return false;

		if ( phase === 1 ) return __csgcVote( 1, String( myTeam ) );
		if ( phase === 5 ) return __csgcVote( 5, '' + ( Math.random() < 0.5 ? 2 : 3 ) );

		for ( var j = 0; j < list.length; j++ )
		{
			var id = list[j];
			if ( !id ) continue;
			var s2 = '';
			try { s2 = '' + MatchDraftAPI.GetIngameMapIdState( id ); } catch ( e ) { continue; }
			if ( s2 === 'veto' || s2 === 'pick' ) continue;
			var nm2 = '';
			try { nm2 = '' + DeepStatsAPI.MapIDToString( parseInt( id ) ); } catch ( e ) { }
			if ( nm2 === __csgcTarget ) continue;
			if ( __csgcVote( phase, id ) ) return true;
		}
		$.Msg( '[csgc] BP只剩目标图，无需再投 phase=' + phase );
		return false;
	}

	function __csgcAutoVote()
	{
		var draft = '', phase = 0, turn = '', turnN = 0, ids = '', uiState = '', myTeam = 0;
		try { draft   = '' + MatchDraftAPI.GetDraft(); }              catch ( e ) { draft   = '(取不到)'; }
		try { phase   = MatchDraftAPI.GetIngamePhase(); }              catch ( e ) { }
		try { turn    = '' + MatchDraftAPI.GetIngameTeamToActNow(); turnN = Number( turn ) || 0; } catch ( e ) { }
		try { ids     = '' + MatchDraftAPI.GetIngameMapIdsList(); }    catch ( e ) { }
		try { uiState = '' + GameStateAPI.GetCSGOGameUIStateName(); }  catch ( e ) { }
		try { myTeam  = GameStateAPI.GetPlayerTeamNumber( MyPersonaAPI.GetXuid() ); } catch ( e ) { }

		var list = ( '' + ids ).split( ',' );
		var states = [];
		for ( var i = 0; i < list.length; i++ )
		{
			var st = '';
			try { st = '' + MatchDraftAPI.GetIngameMapIdState( list[i] ); } catch ( e ) { }
			var nm = '';
			try { nm = '' + DeepStatsAPI.MapIDToString( parseInt( list[i] ) ); } catch ( e ) { }
			states.push( list[i] + ':' + nm + ':' + st );
		}
		var statesStr = states.join( ' ' );

		// ★ 只在**状态变化**时打日志 —— 不会被 BP 之前的主菜单海量调用把额度耗光。
		var sig = draft + '|' + phase + '|' + turn + '|' + myTeam + '|' + uiState + '|' + statesStr;
		if ( sig !== __csgcLastSig )
		{
			__csgcLastSig = sig;
			if ( __csgcLogCount++ < 400 )
				$.Msg( '[csgc] BP状态 ' + sig );
		}

		if ( draft !== 'ingame' ) return;
		if ( !( phase >= 1 ) || phase > 5 ) return;

		var turnKnown = ( turnN === 2 || turnN === 3 );
		var myKnown   = ( myTeam === 2 || myTeam === 3 );

		// 谁该动？
		if ( __csgcMode === 'opp_random' )
		{
			// 我方轮次 -> 一个字都不发，交给人点
			if ( myKnown && turnN === myTeam ) return;
			// 判不出对方是谁就别乱投（比如还没分队 myTeam=0）
			if ( !turnKnown || !myKnown ) return;
		}
		else
		{
			if ( turnN && turnN !== myTeam ) return;
		}

		// 同一个 (phase, 图状态) 只动一次 —— 对方投完状态会变，于是自然进入下一轮
		var vkey = phase + '#' + turnN + '#' + statesStr;
		if ( vkey === __csgcLastVote ) return;

		var done = ( __csgcMode === 'opp_random' )
			? __csgcVoteRandom( phase, list, states )
			: __csgcVoteTarget( phase, list, states, myTeam, turnN, ids );

		// 一律记上：_Update 一秒可能触发好几次，不记就是往 console.log 里灌水。
		// 反正 vkey 里带了 turn 和每张图的状态，轮次一翻或有人投完，vkey 就变了，自然会再动。
		__csgcLastVote = vkey;
	}

"""

MODE_LINE_OLD = "var __csgcMode = 'opp_random';"
TARGET_LINE_OLD = "var __csgcTarget    = 'de_mirage';"

# PREAMBLE 的 banner 是 v10 时代写的：写死了 de_mirage、去重键也还是旧的说法，
# 跟 v12 的实际逻辑已经矛盾。产物是给人看的，这里统一改掉。
STALE_BANNER = (
    "\t//   目标：把所有非 de_mirage 的图 ban 掉；阵营随机。\n"
    "\t//   去重：靠 (phase + 图列表 + 各图状态) 的签名，状态一变才再投一次。\n"
)
FRESH_BANNER = (
    "\t//   干什么由下方 __csgcMode 决定；target 模式下要保的图是 __csgcTarget。\n"
    "\t//   去重：靠 (phase + turn + 各图状态) 的签名 —— 轮次一变、或有人投完，就再动一次。\n"
)

MODES = ( "opp_random", "target" )


def main():
    if len( sys.argv ) < 3:
        print( __doc__ )
        return 2
    src, dst = sys.argv[1], sys.argv[2]
    mode = sys.argv[3] if len( sys.argv ) > 3 else "opp_random"
    tmap = sys.argv[4] if len( sys.argv ) > 4 else "de_mirage"
    if mode not in MODES:
        print( "mode 只能是 %s" % ( MODES, ), file=sys.stderr )
        return 2

    raw = open( src, "rb" ).read()
    bom = b""
    if raw.startswith( b"\xef\xbb\xbf" ):
        bom, raw = raw[:3], raw[3:]
    s = raw.decode( "utf-8" ).replace( "\r\n", "\n" )
    assert "\r" not in s, "还有裸 \\r（原始件行尾不是干净的 CRLF？）"

    assert s.count( ANCHOR_REG ) == 1, "RegisterForUnhandledEvent 锚点不唯一 —— 原始件不对？"
    assert s.count( ANCHOR_UPD ) == 1, "function _Update 锚点不唯一 —— 原始件不对？"

    # Python 的 str.replace 找不到目标时**静默返回原串**。两处参数替换都必须先断言，
    # 否则 argv 会被无声忽略（这正是本项目栽过最多次的一类失败）。
    assert MODE_LINE_OLD in V12_IMPL, "实现块里找不到 mode 行"
    assert TARGET_LINE_OLD in PREAMBLE, "前言里找不到 target 行"

    assert STALE_BANNER in PREAMBLE, "banner 注释对不上（原始件或模板变了？）"
    pre = PREAMBLE.replace( TARGET_LINE_OLD, "var __csgcTarget    = '%s';" % tmap )
    pre = pre.replace( STALE_BANNER, FRESH_BANNER )

    impl = V12_IMPL.replace( MODE_LINE_OLD, "var __csgcMode = '%s';" % mode )
    if mode == "target":
        # 把 "← 当前" 从 opp_random 那行挪到 target 那行（纯注释，但产物是给人看的）
        impl = impl.replace( "（v11 的行为）", "（v11 的行为）  ← 当前" )
        impl = impl.replace( "交给人点  ← 当前", "交给人点" )

    # 注意：这里把 ANCHOR_REG 连同它前面那个 \t 一起替换掉，
    # 所以 "$.RegisterForUnhandledEvent" 这行在产物里**没有前导制表符** —— 与原版一致。
    s = s.replace( ANCHOR_REG, pre + impl + ANCHOR_REG.lstrip( "\t" ) )
    s = s.replace( ANCHOR_UPD, UPD_HOOK )

    # 装载标记（主闭包外，纯状态指示）
    if mode == "target":
        mark = "[csgc] BP 自动投票已装载（target 模式，目标 %s，阵营随机）" % tmap
    else:
        mark = "[csgc] BP 自动投票已装载 v12（对方轮次随机代投，我方轮次人工点）"
    s += (
        "\n// [csgc] 装载标记（主闭包外，纯状态指示）\n"
        "$.Msg( '%s' );\n" % mark
    )

    out = bom + s.encode( "utf-8" )
    open( dst, "wb" ).write( out )
    print( "orig %d bytes -> %s %d bytes (mode=%s%s)"
           % ( len( raw ) + len( bom ), dst, len( out ), mode,
               "" if mode != "target" else ", target=" + tmap ) )
    return 0


if __name__ == "__main__":
    sys.exit( main() )
