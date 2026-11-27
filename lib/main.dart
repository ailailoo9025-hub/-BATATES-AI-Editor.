import 'dart:io';
import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:video_player/video_player.dart';
import 'package:path_provider/path_provider.dart';
import 'package:ffmpeg_kit_flutter_new_full/ffmpeg_kit.dart';
import 'package:ffmpeg_kit_flutter_new_full/return_code.dart';
import 'package:share_plus/share_plus.dart';

const bg = Color(0xFF090B12);
const panel = Color(0xFF131724);
const panel2 = Color(0xFF1A2030);
const purple = Color(0xFF9B7BFF);
const cyan = Color(0xFF53D6D0);
const muted = Color(0xFF929AAF);

void main() => runApp(const BatatesApp());

class BatatesApp extends StatelessWidget {
  const BatatesApp({super.key});
  @override
  Widget build(BuildContext context) => MaterialApp(
    debugShowCheckedModeBanner: false,
    title: 'BATATES AI Editor',
    theme: ThemeData(
      brightness: Brightness.dark,
      scaffoldBackgroundColor: bg,
      colorScheme: const ColorScheme.dark(primary: purple, secondary: cyan, surface: panel),
      useMaterial3: true,
    ),
    home: const EditorHome(),
  );
}

class EditorHome extends StatefulWidget {
  const EditorHome({super.key});
  @override
  State<EditorHome> createState() => _EditorHomeState();
}

class _EditorHomeState extends State<EditorHome> {
  final List<File> clips = [];
  File? chatFile;
  VideoPlayerController? player;
  int active = 0;
  double start = 0;
  double end = 0;
  bool busy = false;
  bool scanning = false;
  final List<Map<String, double>> highlights = [];
  String status = 'Import a video to begin';
  String ratio = '9:16';
  final serverController = TextEditingController(text: 'https://batates-ai-editor.onrender.com');
  final streamController = TextEditingController();
  final chatStreamController = TextEditingController();
  final obsKeyController = TextEditingController();
  final List<Map<String, double>> editSegments = [];
  String chatPlatform = '';
  String? activeJobId;
  bool activeStream = false;
  bool obsMode = false;
  String backendStatus = 'Backend not connected';

  String get apiBase => serverController.text.trim().replaceAll(RegExp(r'/+$'), '');

  Future<void> stopLiveCapture() async {
    final id = activeJobId;
    if (id == null) return;
    try {
      final response = await http.post(Uri.parse('${apiBase}/jobs/$id/stop')).timeout(const Duration(seconds: 20));
      if (response.statusCode < 200 || response.statusCode >= 300) throw Exception(response.body);
      if (mounted) setState(() => backendStatus = 'Stop requested. BATATES is finalizing the montage…');
    } catch (e) {
      if (mounted) setState(() => backendStatus = 'Could not stop live capture: $e');
    }
  }

  Future<void> importVideos() async {
    final result = await FilePicker.platform.pickFiles(type: FileType.video, allowMultiple: true);
    if (result == null) return;
    final files = result.files.where((f) => f.path != null).map((f) => File(f.path!)).toList();
    if (files.isEmpty) {
      setState(() => status = 'Could not access the selected file path. Try choosing a video stored on the device.');
      return;
    }
    setState(() { clips.addAll(files); status = '${files.length} video(s) added'; });
    await selectClip(clips.length - files.length);
  }

  Future<void> selectClip(int index) async {
    if (index < 0 || index >= clips.length) return;
    final old = player;
    player = null;
    await old?.dispose();
    final controller = VideoPlayerController.file(clips[index]);
    try {
      await controller.initialize();
      controller.setLooping(true);
      if (!mounted) { await controller.dispose(); return; }
      setState(() {
        active = index;
        player = controller;
        start = 0;
        end = controller.value.duration.inMilliseconds / 1000.0;
        status = 'Ready to edit: ${clips[index].uri.pathSegments.last}';
      });
    } catch (e) {
      await controller.dispose();
      if (mounted) setState(() => status = 'Preview failed: $e');
    }
  }

  String quote(String s) => '"${s.replaceAll('"', r'\"')}"';

  // First-pass highlight radar: samples audio loudness in short windows.
  // This finds energetic moments, not semantic humor or guaranteed best clips.
  Future<void> scanHighlights() async {
    if (clips.isEmpty || player == null || busy || scanning) return;
    setState(() { scanning = true; highlights.clear(); status = 'Analyzing audio energy…'; });
    try {
      final file = clips[active];
      final duration = player!.value.duration.inSeconds;
      const window = 8;
      final total = (duration / window).ceil().clamp(1, 120);
      final found = <Map<String, double>>[];
      for (var i = 0; i < total; i++) {
        final from = (i * window).toDouble();
        if (from >= duration) break;
        final length = (duration - from).clamp(0, window).toDouble();
        final cmd = '-hide_banner -ss ${from.toStringAsFixed(2)} -t ${length.toStringAsFixed(2)} -i ${quote(file.path)} -vn -af volumedetect -f null -';
        final session = await FFmpegKit.execute(cmd);
        final logs = (await session.getLogs()).map((l) => l.getMessage()).join('\n');
        final match = RegExp(r'max_volume:\s*(-?[0-9.]+)\s*dB').firstMatch(logs);
        final db = match == null ? -60.0 : (double.tryParse(match.group(1)!) ?? -60.0);
        final score = (((db + 55) / 55) * 100).clamp(0, 100).toDouble();
        if (score >= 35 && length >= 3) found.add({'start': from, 'end': from + length, 'score': score});
        if (mounted) setState(() => status = 'Audio scan ${i + 1}/$total…');
      }
      found.sort((a, b) => b['score']!.compareTo(a['score']!));
      final selected = found.take(12).toList()..sort((a, b) => a['start']!.compareTo(b['start']!));
      if (mounted) setState(() { highlights.addAll(selected); status = selected.isEmpty ? 'No strong audio peaks found. Try a recording with clearer sound.' : 'Found ${selected.length} energetic candidate moments. Review before exporting.'; });
    } catch (e) {
      if (mounted) setState(() => status = 'Analysis failed: $e');
    } finally {
      if (mounted) setState(() => scanning = false);
    }
  }

  Future<void> export({bool auto = false}) async {
    if (clips.isEmpty || player == null || busy) return;
    final duration = player!.value.duration.inMilliseconds / 1000.0;
    final best = highlights.isEmpty ? null : (highlights.toList()..sort((a, b) => b['score']!.compareTo(a['score']!))).first;
    final from = auto && best != null ? best['start']! : (auto ? 0.0 : start.clamp(0.0, duration));
    final to = auto && best != null ? best['end']! : (auto ? (duration < 30 ? duration : 30.0) : end.clamp(from + 0.2, duration));
    final ranges = auto ? <Map<String,double>>[{'start':from,'end':to}] :
      (editSegments.isEmpty ? <Map<String,double>>[{'start':from,'end':to}] : List<Map<String,double>>.from(editSegments));
    if (ranges.any((r) => r['end']! - r['start']! < 0.2)) {
      setState(() => status = 'Choose longer timeline segments before exporting.');
      return;
    }
    setState(() { busy = true; status = auto ? 'Preparing the highest-scored candidate edit…' : 'Exporting your trimmed video…'; });
    try {
      final dir = await getApplicationDocumentsDirectory();
      final stamp = DateTime.now().millisecondsSinceEpoch;
      final output = '${dir.path}/BATATES_$stamp.mp4';
      final vf = ratio == '9:16'
          ? 'scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920'
          : 'scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2';
      final parts = <String>[];
      for (var i=0; i<ranges.length; i++) {
        final r = ranges[i];
        final part = '${dir.path}/BATATES_${stamp}_part_$i.mp4';
        final command = '-y -ss ${r['start']!.toStringAsFixed(2)} -i ${quote(clips[active].path)} -t ${(r['end']!-r['start']!).toStringAsFixed(2)} -vf "$vf" -c:v mpeg4 -q:v 4 -c:a aac -b:a 160k -movflags +faststart ${quote(part)}';
        final session = await FFmpegKit.execute(command);
        if (!ReturnCode.isSuccess(await session.getReturnCode()) || !await File(part).exists()) {
          throw Exception('Could not render timeline segment ${i+1}.');
        }
        parts.add(part);
      }
      if (parts.length == 1) {
        await File(parts.first).copy(output);
      } else {
        final listing = '${dir.path}/BATATES_${stamp}_concat.txt';
        await File(listing).writeAsString(parts.map((p) => "file '$p'\n").join());
        final joined = await FFmpegKit.execute('-y -f concat -safe 0 -i ${quote(listing)} -c copy -movflags +faststart ${quote(output)}');
        if (!ReturnCode.isSuccess(await joined.getReturnCode())) throw Exception('Could not join timeline segments.');
      }
      if (await File(output).exists()) {
        if (!mounted) return;
        setState(() => status = 'Export complete: $output');
        await Share.shareXFiles([XFile(output)], text: 'Created with BATATES AI Editor');
      } else {
        throw Exception('FFmpeg export did not create the output file.');
      }
    } catch (e) {
      if (mounted) setState(() => status = 'Export error: $e');
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  void dispose() { player?.dispose(); serverController.dispose(); streamController.dispose(); chatStreamController.dispose(); obsKeyController.dispose(); super.dispose(); }

  @override
  Widget build(BuildContext context) => Scaffold(
    body: SafeArea(child: LayoutBuilder(builder: (context, c) {
      final wide = c.maxWidth > 760;
      return Column(children: [
        _header(),
        Expanded(child: wide ? Row(children: [
          SizedBox(width: 250, child: _library()),
          const VerticalDivider(width: 1, color: Color(0xFF252B3A)),
          Expanded(child: _workspace()),
        ]) : _mobileBody()),
      ]);
    })),
  );

  Widget _header() => Container(
    padding: const EdgeInsets.symmetric(horizontal: 22, vertical: 16),
    decoration: const BoxDecoration(color: Color(0xFF0D111B), border: Border(bottom: BorderSide(color: Color(0xFF252B3A)))),
    child: Row(children: [
      Container(width: 42, height: 42, decoration: BoxDecoration(gradient: const LinearGradient(colors: [purple, cyan]), borderRadius: BorderRadius.circular(13)), child: const Icon(Icons.movie_filter_rounded, color: Colors.black)),
      const SizedBox(width: 12),
      const Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('BATATES AI', style: TextStyle(fontWeight: FontWeight.w900, letterSpacing: 1.2)),
        Text('EDITOR  •  STUDIO', style: TextStyle(fontSize: 10, color: muted, letterSpacing: 2)),
      ]),
      const Spacer(),
      const Icon(Icons.cloud_done_rounded, color: cyan, size: 17),
      const SizedBox(width: 6),
      const Text('AI CLOUD + LOCAL EDITOR', style: TextStyle(color: muted, fontSize: 10, letterSpacing: 1)),
    ]),
  );

  Widget _mobileBody() => ListView(children: [_library(), _workspace()]);
  Widget _library() => Container(
    color: const Color(0xFF0D111B), padding: const EdgeInsets.all(16),
    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      const Text('PROJECT MEDIA', style: TextStyle(color: muted, fontWeight: FontWeight.bold, letterSpacing: 1.4, fontSize: 11)),
      const SizedBox(height: 12),
      SizedBox(width: double.infinity, child: FilledButton.icon(
        onPressed: busy ? null : importVideos,
        icon: const Icon(Icons.add_to_photos_rounded),
        label: const Text('Import video / استيراد فيديو'),
      )),
      const SizedBox(height: 12),
      if (clips.isEmpty) const Padding(padding: EdgeInsets.symmetric(vertical: 20), child: Center(child: Text('Your imported videos appear here', style: TextStyle(color: muted))))
      else ...List.generate(clips.length, (i) => ListTile(
        dense: true, selected: i == active, selectedTileColor: panel2,
        leading: const Icon(Icons.video_file_rounded, color: cyan),
        title: Text(clips[i].uri.pathSegments.last, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 12)),
        onTap: () => selectClip(i),
      )),
    ]),
  );

  Widget _workspace() => LayoutBuilder(builder: (context, constraints) {
    final compact = constraints.maxWidth < 760;
    return Padding(
    padding: const EdgeInsets.all(18),
    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      const Text('WORKSPACE', style: TextStyle(color: muted, fontSize: 10, letterSpacing: 1.5, fontWeight: FontWeight.bold)),
      const SizedBox(height: 8),
      Card(color: panel, child: Padding(padding: const EdgeInsets.all(14), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [const Icon(Icons.sensors_rounded, color: cyan), const SizedBox(width: 8), const Text('LIVE CLIP CAPTURE', style: TextStyle(fontWeight: FontWeight.w800, letterSpacing: 1))]),
        const SizedBox(height: 6),
        const Text('استقبل بثًا عامًا أو بث OBS، ثم اجمع اللقطات المرشحة في كليبات.', style: TextStyle(color: muted, fontSize: 11)),
        const SizedBox(height: 12),
        SegmentedButton<bool>(segments: const [
          ButtonSegment(value: false, label: Text('رابط بث')),
          ButtonSegment(value: true, label: Text('OBS')),
        ], selected: {obsMode}, onSelectionChanged: busy ? null : (v) => setState(() => obsMode = v.first)),
        const SizedBox(height: 10),
        if (!obsMode) TextField(controller: streamController, enabled: !busy, decoration: const InputDecoration(labelText: 'رابط البث العام', hintText: 'https://…', prefixIcon: Icon(Icons.link))),
        if (obsMode) TextField(controller: obsKeyController, enabled: !busy, decoration: const InputDecoration(labelText: 'مفتاح بث BATATES', hintText: '8-80 characters', prefixIcon: Icon(Icons.key))),
        const SizedBox(height: 10),
        DropdownButtonFormField<String>(value: chatPlatform.isEmpty ? null : chatPlatform, decoration: const InputDecoration(labelText: 'تحليل الشات (اختياري)'), items: const [
          DropdownMenuItem(value: '', child: Text('بدون شات')),
          DropdownMenuItem(value: 'twitch', child: Text('Twitch')),
          DropdownMenuItem(value: 'youtube', child: Text('YouTube')),
        ], onChanged: busy ? null : (v) => setState(() => chatPlatform = v ?? '')),
        if (chatPlatform.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 10), child: TextField(controller: chatStreamController, enabled: !busy, decoration: const InputDecoration(labelText: 'معرّف البث للشات', prefixIcon: Icon(Icons.tag)))),
        const SizedBox(height: 10),
        SizedBox(width: double.infinity, child: FilledButton.icon(onPressed: busy ? null : () => sendToBackend(stream: !obsMode, obs: obsMode), icon: const Icon(Icons.play_arrow_rounded), label: const Text('ابدأ استقبال البث وتحليل اللقطات'))),
        if (activeStream) Padding(padding: const EdgeInsets.only(top: 8), child: SizedBox(width: double.infinity, child: OutlinedButton.icon(onPressed: stopLiveCapture, icon: const Icon(Icons.stop_circle_outlined), label: const Text('إيقاف البث وإنهاء الكليبات')))),
        const SizedBox(height: 8),
        const Text('تنبيه: روابط صفحات البث قد لا تعمل دائمًا. خيار OBS يحتاج MediaMTX منشورًا ومربوطًا بالخادم؛ Render الحالي لا يحتوي عليه بعد.', style: TextStyle(color: muted, fontSize: 10)),
        Text(backendStatus, style: const TextStyle(color: cyan, fontSize: 11)),
      ]))),
      const SizedBox(height: 14),
      Wrap(spacing: 10, runSpacing: 10, crossAxisAlignment: WrapCrossAlignment.center, children: [
        const Text('AI QUICK EDIT', style: TextStyle(fontWeight: FontWeight.w900, fontSize: 18)),
        _chip('Auto edit'),
        _chip('Trim'),
        _chip('Export'),
      ]),
      const SizedBox(height: 12),
      SizedBox(width: double.infinity, child: FilledButton.icon(
        style: FilledButton.styleFrom(backgroundColor: purple, foregroundColor: Colors.white, padding: const EdgeInsets.symmetric(vertical: 18)),
        onPressed: busy || scanning ? null : (clips.isEmpty ? importVideos : () => sendToBackend()),
        icon: const Icon(Icons.auto_awesome_rounded, size: 22),
        label: const Text('ارفع فيديو وخلي BATATES يضبطه', style: TextStyle(fontSize: 15, fontWeight: FontWeight.bold)),
      )),
      const SizedBox(height: 8),
      const Text('ارفع فيديو مسجّل، وسيحلله BATATES ويجهّز لك أفضل المقاطع. المعالجة تتم عبر خادم BATATES.', style: TextStyle(color: muted, fontSize: 11)),
      const SizedBox(height: 12),
      TextField(controller: serverController, decoration: const InputDecoration(labelText: 'BATATES backend URL', hintText: 'https://your-server.example', prefixIcon: Icon(Icons.cloud_outlined))),
      const SizedBox(height: 8),
      SizedBox(width: double.infinity, child: OutlinedButton.icon(
        onPressed: busy || clips.isEmpty ? null : () => sendToBackend(),
        icon: const Icon(Icons.auto_awesome),
        label: const Text('حلّل الفيديو واصنع المقاطع تلقائيًا'),
      )),
      OutlinedButton.icon(
        onPressed: busy ? null : importChatFile,
        icon: const Icon(Icons.chat_bubble_outline),
        label: Text(chatFile == null ? 'إرفاق شات بصيغة JSON (اختياري)' : 'تم إرفاق ملف الشات'),
      ),
      const Text('الفيديو المسجّل: تحليل المرشحات، مراجعتها، ثم تصديرها من جهازك.', style: TextStyle(color: muted, fontSize: 10)),
      Text(backendStatus, style: const TextStyle(color: cyan, fontSize: 11)),


      const SizedBox(height: 10),
      SizedBox(width: double.infinity, child: OutlinedButton.icon(
        onPressed: clips.isEmpty || busy || scanning ? null : scanHighlights,
        icon: scanning ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2)) : const Icon(Icons.radar_rounded),
        label: Text(scanning ? 'Analyzing audio…' : 'اكتشف اللقطات الحماسية • Scan highlights'),
      )),
      if (highlights.isNotEmpty) ...[
        const SizedBox(height: 12),
        const Text('HIGHLIGHT CANDIDATES', style: TextStyle(color: cyan, fontSize: 11, fontWeight: FontWeight.bold)),
        ...highlights.map((h) => ListTile(
          dense: true, contentPadding: EdgeInsets.zero,
          leading: const Icon(Icons.bolt_rounded, color: cyan),
          title: Text('${h['start']!.toStringAsFixed(1)}s – ${h['end']!.toStringAsFixed(1)}s'),
          subtitle: Text('Audio energy score • ${h['score']!.round()}/100'),
          trailing: IconButton(icon: const Icon(Icons.edit_outlined), onPressed: () => setState(() { start = h['start']!; end = h['end']!; status = 'Candidate selected. Preview and export when ready.'; })),
        )),
      ],
      const SizedBox(height: 16),
      if (compact)
        SizedBox(height: 220, child: _preview())
      else
        Expanded(child: _preview()),
      const SizedBox(height: 14),
      Row(children: [
        const Text('OUTPUT FORMAT', style: TextStyle(color: muted, fontSize: 10, fontWeight: FontWeight.bold)),
        const Spacer(),
        SegmentedButton<String>(segments: const [
          ButtonSegment(value: '9:16', label: Text('9:16')),
          ButtonSegment(value: '16:9', label: Text('16:9')),
        ], selected: {ratio}, onSelectionChanged: (s) => setState(() => ratio = s.first)),
      ]),
      const SizedBox(height: 10),
      if (player != null) ...[
        Row(children: [const Text('Trim start', style: TextStyle(color: muted)), const Spacer(), Text('${start.toStringAsFixed(1)}s')]),
        Slider(value: start.clamp(0, (end - .2).clamp(0, 999999)), min: 0, max: (player!.value.duration.inMilliseconds / 1000).clamp(1, 999999).toDouble(), onChanged: (v) => setState(() { start = v; if (end <= start + .2) end = start + .2; })),
        Row(children: [const Text('Trim end', style: TextStyle(color: muted)), const Spacer(), Text('${end.toStringAsFixed(1)}s')]),
        Slider(value: end.clamp((start + .2).clamp(0, 999999), (player!.value.duration.inMilliseconds / 1000).clamp(1, 999999).toDouble()), min: 0, max: (player!.value.duration.inMilliseconds / 1000).clamp(1, 999999).toDouble(), onChanged: (v) => setState(() => end = v)),
        const SizedBox(height: 6),
        SizedBox(width: double.infinity, child: OutlinedButton.icon(
          onPressed: busy ? null : () {
            if (end - start < 0.2) return;
            setState(() {
              editSegments.add({'start':start,'end':end});
              status = 'Added segment ${editSegments.length} to editable timeline.';
            });
          },
          icon: const Icon(Icons.playlist_add),
          label: const Text('أضف المقطع المحدد إلى الـ Timeline'),
        )),
      ] else const Text('Trim controls appear after importing a video.', style: TextStyle(color: muted)),
      if (editSegments.isNotEmpty) ...[
        const SizedBox(height: 10),
        Text('EDIT TIMELINE • ${editSegments.length} segments', style: const TextStyle(color: cyan, fontSize: 11, fontWeight: FontWeight.bold)),
        ...List.generate(editSegments.length, (i) => ListTile(
          dense: true, contentPadding: EdgeInsets.zero,
          leading: Text('#${i+1}', style: const TextStyle(color: cyan)),
          title: Text('${editSegments[i]['start']!.toStringAsFixed(1)}s — ${editSegments[i]['end']!.toStringAsFixed(1)}s'),
          trailing: IconButton(icon: const Icon(Icons.close), onPressed: () => setState(() => editSegments.removeAt(i))),
        )),
        TextButton.icon(onPressed: () => setState(() => editSegments.clear()), icon: const Icon(Icons.delete_outline), label: const Text('مسح الـ Timeline')),
      ],
      const SizedBox(height: 8),
      SizedBox(width: double.infinity, child: FilledButton.icon(
        onPressed: busy || clips.isEmpty ? null : () => export(),
        icon: busy ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2)) : const Icon(Icons.file_upload_outlined),
        label: Text(busy ? 'Working…' : 'Export edited video'),
      )),
      const SizedBox(height: 8),
      Text(status, maxLines: 3, overflow: TextOverflow.ellipsis, style: const TextStyle(color: muted, fontSize: 11)),
    ]),
  );
  });

  Widget _preview() => Container(
    width: double.infinity,
    decoration: BoxDecoration(color: Colors.black, borderRadius: BorderRadius.circular(18), border: Border.all(color: const Color(0xFF293044))),
    child: player == null ? const Center(child: Column(mainAxisSize: MainAxisSize.min, children: [
      Icon(Icons.play_circle_outline_rounded, size: 54, color: muted),
      SizedBox(height: 8), Text('Import a video to preview', style: TextStyle(color: muted)),
    ])) : ClipRRect(borderRadius: BorderRadius.circular(18), child: Stack(alignment: Alignment.center, children: [
      Center(child: AspectRatio(aspectRatio: player!.value.aspectRatio, child: VideoPlayer(player!))),
      IconButton.filledTonal(onPressed: () => setState(() => player!.value.isPlaying ? player!.pause() : player!.play()), iconSize: 32, icon: Icon(player!.value.isPlaying ? Icons.pause : Icons.play_arrow)),
      Positioned(left: 12, bottom: 12, child: Text('${player!.value.position.inSeconds}s / ${player!.value.duration.inSeconds}s', style: const TextStyle(backgroundColor: Colors.black54))),
    ])),
  );

  Widget _chip(String label) => Container(padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6), decoration: BoxDecoration(color: panel2, borderRadius: BorderRadius.circular(20)), child: Text(label, style: const TextStyle(fontSize: 10, color: cyan)));

  Future<void> importChatFile() async {
    final result = await FilePicker.platform.pickFiles(type: FileType.custom, allowedExtensions: ['json']);
    if (result == null || result.files.single.path == null) return;
    if (!mounted) return;
    setState(() {
      chatFile = File(result.files.single.path!);
      backendStatus = 'Chat file attached: ${result.files.single.name}';
    });
  }

  Future<void> sendToBackend({bool stream = false, bool obs = false}) async {
    if (busy) return;
    final base = apiBase;
    if (!base.startsWith('http://') && !base.startsWith('https://')) {
      setState(() => backendStatus = 'Enter a valid backend URL first.');
      return;
    }
    if (stream && !obs && streamController.text.trim().isEmpty) {
      setState(() => backendStatus = 'Paste a supported direct stream media URL first.');
      return;
    }
    if (!stream && clips.isEmpty) {
      setState(() => backendStatus = 'Import a video first.');
      return;
    }
    setState(() {
      busy = true;
      activeStream = stream || obs;
      backendStatus = obs ? 'Connecting OBS ingest…' : (stream ? 'Resolving live stream page…' : 'Uploading video for AI analysis…');
    });
    try {
      late http.Response response;
      if (obs) {
        response = await http.post(
          Uri.parse('$base/jobs/obs'),
          headers: {'Content-Type':'application/json'},
          body: jsonEncode({
            'stream_key': obsKeyController.text.trim(),
            'ratio': ratio,
            'platform': chatPlatform,
            'chat_stream_id': chatStreamController.text.trim(),
            'max_seconds': 3600,
          }),
        ).timeout(const Duration(seconds: 60));
      } else if (stream) {
        response = await http.post(
          Uri.parse('$base/jobs/stream'),
          body: {
            'url': streamController.text.trim(),
            'ratio': ratio,
            'platform': chatPlatform,
            'chat_stream_id': chatStreamController.text.trim(),
            'max_seconds': '3600',
          },
        ).timeout(const Duration(seconds: 60));
      } else {
        final request = http.MultipartRequest('POST', Uri.parse('$base/jobs/upload'))
          ..fields['ratio'] = ratio
          ..files.add(await http.MultipartFile.fromPath('video', clips[active].path));
        if (chatFile != null) {
          request.files.add(await http.MultipartFile.fromPath('chat', chatFile!.path));
        }
        final streamed = await request.send().timeout(const Duration(minutes: 15));
        response = await http.Response.fromStream(streamed);
      }
      if (response.statusCode < 200 || response.statusCode >= 300) {
        throw Exception(response.body);
      }
      final job = jsonDecode(response.body) as Map<String, dynamic>;
      final id = job['job_id'] as String;
      if (mounted) {
        setState(() {
          activeJobId = id;
          backendStatus = 'BATATES is analyzing job $id…';
        });
      }
      for (var attempt = 0; attempt < 1200; attempt++) {
        await Future.delayed(const Duration(seconds: 3));
        final check = await http.get(Uri.parse('$base/jobs/$id')).timeout(const Duration(seconds: 30));
        if (check.statusCode != 200) throw Exception('Could not read job status: ${check.body}');
        final data = jsonDecode(check.body) as Map<String, dynamic>;
        final state = data['status']?.toString() ?? 'unknown';
        if (mounted) {
          setState(() => backendStatus = 'AI job $id: $state • clips: ${data['clips_ready'] ?? 0}');
        }
        if (state == 'failed') throw Exception(data['error'] ?? 'Processing failed');
        if (state == 'clips_available' && mounted) {
          setState(() => backendStatus = 'تم اكتشاف ${data['clips_ready'] ?? 0} كليب حتى الآن… أوقف البث لإنهاء التصدير.');
        }
        if (state == 'complete') {
          final fileResponse = await http.get(Uri.parse('$base/jobs/$id/download')).timeout(const Duration(minutes: 15));
          if (fileResponse.statusCode != 200) throw Exception('Output download failed');
          final dir = await getApplicationDocumentsDirectory();
          final output = File('${dir.path}/BATATES_${DateTime.now().millisecondsSinceEpoch}.mp4');
          await output.writeAsBytes(fileResponse.bodyBytes);
          final clipResponse = await http.get(Uri.parse('$base/jobs/$id/clips')).timeout(const Duration(seconds: 30));
          final readyClips = <XFile>[];
          if (clipResponse.statusCode == 200) {
            final clipData = jsonDecode(clipResponse.body) as Map<String, dynamic>;
            final items = (clipData['clips'] as List<dynamic>? ?? []).take(10);
            var clipNumber = 0;
            for (final item in items) {
              final relative = (item as Map<String, dynamic>)['download']?.toString();
              if (relative == null) continue;
              final clipFile = await http.get(Uri.parse('$base$relative')).timeout(const Duration(minutes: 5));
              if (clipFile.statusCode != 200) continue;
              clipNumber++;
              final clipPath = '${dir.path}/BATATES_${DateTime.now().millisecondsSinceEpoch}_clip_$clipNumber.mp4';
              final saved = File(clipPath);
              await saved.writeAsBytes(clipFile.bodyBytes);
              readyClips.add(XFile(saved.path));
            }
          }
          await SharePlus.instance.share(ShareParams(
            files: readyClips.isEmpty ? [XFile(output.path)] : readyClips,
            text: 'Created with BATATES AI Editor',
          ));
          if (mounted) {
            setState(() {
              backendStatus = 'Finished! Your montage is ready to share.';
              activeStream = false;
              activeJobId = null;
            });
          }
          return;
        }
      }
      throw Exception('Processing timed out. Check the backend job status.');
    } catch (e) {
      if (mounted) {
        setState(() {
          backendStatus = 'Backend error: $e';
          activeStream = false;
          activeJobId = null;
        });
      }
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

}
