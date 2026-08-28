package com.openai.e87probe;

import java.util.Arrays;
import java.util.List;
import java.util.UUID;

public final class ProbeCoreTest {
    public static void main(String[] args) {
        testHexRoundTrip();
        testQixFactoryMemoryReadContract();
        testQixFragmentedBindResponse();
        testQixBindFirmwareVersion();
        testQixFirmwareUpdateHeaderProbe();
        testQixFirmwareUpdateTransferFrames();
        testTargetInfoRequest();
        testResponseParsing();
        testFragmentedFrameAssemblyAndResync();
        testAuthHandshake();
        testTargetInfoDecision();
        testStorageQueryFrame();
        testRootBrowseFrames();
        testBrowseDataExtractionAndDirectoryParsing();
        testBrowseDataAndDirectoryRejections();
        testStopBrowseCommandParsing();
        testBoundedRootBrowseSession();
        testLegacyStorageHandleParsing();
        testLiveBadgeFilesystemHandleParsing();
        testVersionedStorageHandleParsing();
        testStorageProbeDecisions();
        testAdvertisementGate();
        testConnectionRetryGate();
        testRunStateConsumesDuplicateResponses();
        testRunStateUsesAbsoluteBrowseDeadline();
        System.out.println("ProbeCoreTest: PASS");
    }

    private static void testHexRoundTrip() {
        byte[] bytes = {(byte) 0xFE, 0x00, 0x2A};
        equal("FE002A", Hex.encode(bytes), "hex encode");
        bytes(bytes, Hex.decode("fe 00:2a"), "hex decode");
    }

    private static void testQixFactoryMemoryReadContract() {
        byte[] expected = Hex.decode("9E4382A90600000200001000");
        byte[] request = QixFactoryMemoryRead.request();
        bytes(expected, request, "factory memory-read request bytes");
        request[0] = 0;
        bytes(expected, QixFactoryMemoryRead.request(),
                "factory memory-read request cannot be mutated by a caller");
        equal("fd01", QixFactoryMemoryRead.channelName(UUID.fromString(
                        "c2e6fd01-e966-1000-8000-bef9c223df6a")),
                "FD01 notification channel recognized");
        equal("fd03", QixFactoryMemoryRead.channelName(UUID.fromString(
                        "c2e6fd03-e966-1000-8000-bef9c223df6a")),
                "FD03 notification channel recognized");
        equal(true, QixFactoryMemoryRead.channelName(UUID.fromString(
                        "c2e6fd02-e966-1000-8000-bef9c223df6a")) == null,
                "unsubscribed characteristic rejected");

        bytes(Hex.decode("9EC502600D0002443322110000443322110000"),
                QixFactoryMemoryRead.bindRequest(0x02, 0x11223344),
                "vendor bind request preserves the 6-byte repeated host identifier");
        bytes(Hex.decode("9E4B8AA90600000200001000"),
                QixFactoryMemoryRead.request(1),
                "memory read after bind uses Qix serial one");
        equal(true, QixFactoryMemoryRead.isSuccessfulBindResponse(
                        Hex.decode("9E630161010000")),
                "opcode 61 state zero advances the bind-then-read sequence");
        equal(false, QixFactoryMemoryRead.isSuccessfulBindResponse(
                        Hex.decode("9E640161010001")),
                "nonzero bind state does not advance the sequence");
        equal(false, QixFactoryMemoryRead.isSuccessfulBindResponse(
                        Hex.decode("9E620160010000")),
                "generic opcode 60 traffic cannot masquerade as a bind response");
        equal(true, QixFactoryMemoryRead.requestsResponse(
                        Hex.decode("9E640261010000")),
                "incoming flag bit one triggers the stock generic response");
        bytes(Hex.decode("9E6B09FF02006100"),
                QixFactoryMemoryRead.successResponse(0x61, 1),
                "bind response acknowledgement uses the next Qix serial");
        bytes(Hex.decode("9E5392A90600000200001000"),
                QixFactoryMemoryRead.request(2),
                "memory read after bind response acknowledgement uses serial two");
    }

    private static void testQixFragmentedBindResponse() {
        QixFrameAssembler assembler = new QixFrameAssembler();
        byte[] first = Hex.decode("9E8C0C611E0000322E3731312E312E302E330000");
        byte[] second = Hex.decode("0006060080104001000020312E302E30");
        equal(true, assembler.append(first) == null,
                "first live bind fragment waits for its continuation");
        bytes(Hex.decode("9E8C0C611E0000322E3731312E312E302E330000"
                        + "0006060080104001000020312E302E30"),
                assembler.append(second),
                "live 20+16-byte bind response is reassembled exactly");
    }

    private static void testQixBindFirmwareVersion() {
        equal("11.1.0.3", QixFactoryMemoryRead.bindFirmwareVersion(Hex.decode(
                        "9E8C0C611E0000322E3731312E312E302E330000"
                                + "0006060080104001000020312E302E30")),
                "live bind response exposes the ten-byte firmware version field");
        throwsIllegalArgument(
                () -> QixFactoryMemoryRead.bindFirmwareVersion(
                        Hex.decode("9E630161010000")),
                "short bind response cannot masquerade as version-bearing response");
    }

    private static void testQixFirmwareUpdateHeaderProbe() {
        byte[] header = Hex.decode(
                "BCAF01312E30000000000000000800000000000000000000001234");
        bytes(Hex.decode(
                        "9E2905C01B00BCAF01312E30000000000000000800000000000000000000001234"),
                QixFirmwareUpdateProbe.start(header),
                "vendor C0 request carries an opaque exact 27-byte header");
        QixFirmwareUpdateProbe.UpdateRequest response =
                QixFirmwareUpdateProbe.parseUpdateRequest(
                        Hex.decode("9EBC01C1090001F000000000000000"));
        equal(1, response.state, "C1 state one accepts the update");
        equal(240, response.allowedLength, "C1 little-endian write window parsed");
        equal(0, response.offset, "C1 little-endian resume offset parsed");
    }

    private static void testQixFirmwareUpdateTransferFrames() {
        byte[] payload = Hex.decode("00010203040506070809");
        bytes(Hex.decode("9EEB09C20C00040000000200000002030405"),
                QixFirmwareUpdateProbe.dataBlock(payload, 2, 4, 1),
                "C2 encodes chunk length, absolute payload offset, and exact data slice");
        bytes(Hex.decode("9E727DC20F00070000000100000001020304050607"),
                QixFirmwareUpdateProbe.dataBlock(payload, 1, 7, 15),
                "C2 sets the fragmented-frame flag and preserves serial fifteen");

        QixFirmwareUpdateProbe.DataResponse data =
                QixFirmwareUpdateProbe.parseDataResponse(
                        Hex.decode("9ECD01C305000000040000"));
        equal(0, data.result, "C3 result zero accepts the data block");
        equal(1024, data.nextOffset, "C3 next offset is little-endian");

        equal(0, QixFirmwareUpdateProbe.parseUpdateResult(
                        Hex.decode("9EC701C5010000")),
                "C5 result zero completes the update");
        throwsIllegalArgument(
                () -> QixFirmwareUpdateProbe.dataBlock(payload, 8, 4, 1),
                "C2 rejects a data slice beyond the payload");
        throwsIllegalArgument(
                () -> QixFirmwareUpdateProbe.parseDataResponse(
                        Hex.decode("9ECC01C305000000040000")),
                "C3 rejects a corrupt checksum");
    }

    private static void testTargetInfoRequest() {
        bytes(
                Hex.decode("FEDCBAC003000611FFFFFFFF00EF"),
                RcspProtocol.targetInfo(0x11),
                "GET_TARGET_INFO");
    }

    private static void testResponseParsing() {
        RcspProtocol.Frame frame = RcspProtocol.parse(
                Hex.decode("FEDCBA000300050044A1B2C3EF"));
        equal(0x03, frame.opcode, "response opcode");
        equal(0, frame.status(), "response status");
        equal(0x44, frame.sequence(), "response sequence");
        bytes(Hex.decode("A1B2C3"), frame.data(), "response data");
        throwsIllegalArgument(
                () -> RcspProtocol.parse(Hex.decode("FEDCBA400300020001EF")),
                "invalid RCSP response flags rejected");
        throwsIllegalArgument(
                () -> RcspProtocol.parse(Hex.decode("FEDCBA00030000EF")),
                "zero-byte response payload rejected");
        throwsIllegalArgument(
                () -> RcspProtocol.parse(Hex.decode("FEDCBA0003000100EF")),
                "one-byte response payload rejected");
    }

    private static void testStorageQueryFrame() {
        bytes(
                Hex.decode("FEDCBAC007000604FF00000004EF"),
                RcspProtocol.storageInfo(0x04),
                "GET_SYS_INFO storage query");
    }

    private static void testRootBrowseFrames() {
        bytes(
                Hex.decode("FEDCBAC00C000F03000A000100000002000400000000EF"),
                RcspProtocol.startRootBrowse(0x03, 0x00000002L),
                "START_FILE_BROWSE one root page");
        bytes(
                Hex.decode("FEDCBA000D0003007A01EF"),
                RcspProtocol.stopBrowseAck(0x7A, 0x01),
                "STOP_FILE_BROWSE acknowledgement echoes sequence and reason");
        throwsIllegalArgument(
                () -> RcspProtocol.startRootBrowse(0x03, -1),
                "negative browse storage handle rejected");
        throwsIllegalArgument(
                () -> RcspProtocol.stopBrowseAck(0x7A, 0x100),
                "out-of-range stop reason rejected");
    }

    private static void testBrowseDataExtractionAndDirectoryParsing() {
        RcspProtocol.Frame firstChunk = RcspProtocol.parse(Hex.decode(
                "FEDCBA80010007550C0800000011EF"));
        RcspProtocol.Frame secondChunk = RcspProtocol.parse(Hex.decode(
                "FEDCBA8001000B560C000106420041004700EF"));
        byte[] utf16Record = concatenate(
                RcspProtocol.extractBrowseData(firstChunk),
                RcspProtocol.extractBrowseData(secondChunk));
        RootDirectoryPage utf16Page = RootDirectoryPage.parse(utf16Record, 10);
        equal(1, utf16Page.entries.size(), "split UTF-16LE record count");
        RootDirectoryPage.Entry bag = utf16Page.entries.get(0);
        equal(false, bag.file, "BAG is a directory");
        equal(2, bag.deviceIndex, "BAG device index");
        equal(0x11L, bag.cluster, "BAG cluster");
        equal(1, bag.ordinal, "BAG ordinal");
        equal(false, bag.gbk, "BAG encoding flag");
        equal("BAG", bag.name, "BAG UTF-16LE name");
        equal("count=1\n"
                        + "0\tdirectory\tdevIndex=2\tcluster=0x00000011\tordinal=1"
                        + "\tencoding=UTF-16LE\tnameUtf8Hex=424147\tname=BAG\n",
                utf16Page.toEvidenceText(),
                "deterministic decoded listing evidence");

        RootDirectoryPage gbkPage = RootDirectoryPage.parse(
                Hex.decode("0B000000220002076F74612E62696E"), 10);
        equal(1, gbkPage.entries.size(), "GBK record count");
        RootDirectoryPage.Entry ota = gbkPage.entries.get(0);
        equal(true, ota.file, "ota.bin is a file");
        equal(2, ota.deviceIndex, "ota.bin device index");
        equal(0x22L, ota.cluster, "ota.bin cluster");
        equal(2, ota.ordinal, "ota.bin ordinal");
        equal(true, ota.gbk, "ota.bin encoding flag");
        equal("ota.bin", ota.name, "ota.bin GBK name");
    }

    private static void testBrowseDataAndDirectoryRejections() {
        throwsIllegalArgument(
                () -> RcspProtocol.extractBrowseData(RcspProtocol.parse(
                        Hex.decode("FEDCBA80010002550DEF"))),
                "wrong embedded browse opcode rejected");
        throwsIllegalArgument(
                () -> RcspProtocol.extractBrowseData(RcspProtocol.parse(
                        Hex.decode("FEDCBA000100020000EF"))),
                "response-shaped outer data frame rejected");
        throwsIllegalArgument(
                () -> RootDirectoryPage.parse(Hex.decode("08000000110001064200"), 10),
                "truncated directory name rejected");
        throwsIllegalArgument(
                () -> RootDirectoryPage.parse(Hex.decode("080000001100010141"), 10),
                "malformed UTF-16LE name rejected strictly");
        byte[] elevenEntries = Hex.decode(
                "0800000000000000" + "0800000000000000"
                        + "0800000000000000" + "0800000000000000"
                        + "0800000000000000" + "0800000000000000"
                        + "0800000000000000" + "0800000000000000"
                        + "0800000000000000" + "0800000000000000"
                        + "0800000000000000");
        throwsIllegalArgument(
                () -> RootDirectoryPage.parse(elevenEntries, 10),
                "directory page above ten records rejected");
    }

    private static void testStopBrowseCommandParsing() {
        RcspProtocol.StopBrowseCommand stop = RcspProtocol.extractStopBrowseCommand(
                RcspProtocol.parse(Hex.decode("FEDCBAC00D00027A01EF")));
        equal(0x7A, stop.sequence, "stop command sequence");
        equal(0x01, stop.reason, "stop command reason");
        throwsIllegalArgument(
                () -> RcspProtocol.extractStopBrowseCommand(RcspProtocol.parse(
                        Hex.decode("FEDCBA800D00027A01EF"))),
                "stop command without response request rejected");
        throwsIllegalArgument(
                () -> RcspProtocol.extractStopBrowseCommand(RcspProtocol.parse(
                        Hex.decode("FEDCBA000D0003007A01EF"))),
                "stop response cannot be mistaken for stop command");
    }

    private static void testBoundedRootBrowseSession() {
        byte[] record = Hex.decode("0800000011000106420041004700");
        RootBrowseSession session = new RootBrowseSession();
        throwsIllegalState(
                () -> session.appendData(Arrays.copyOfRange(record, 0, 5)),
                "browse data before accepted start rejected");
        session.acceptStartResponse(0);
        session.appendData(Arrays.copyOfRange(record, 0, 5));
        session.appendData(Arrays.copyOfRange(record, 5, record.length));
        bytes(record, session.rawData(), "browse session preserves split bytes");
        RootDirectoryPage page = session.finish();
        equal(1, page.entries.size(), "browse session parsed entry count");
        equal("BAG", page.entries.get(0).name, "browse session parsed entry name");
        throwsIllegalState(
                () -> session.appendData(new byte[0]),
                "browse data after finish rejected");

        RootBrowseSession failedStart = new RootBrowseSession();
        throwsIllegalArgument(
                () -> failedStart.acceptStartResponse(1),
                "failed browse start rejected");

        RootBrowseSession bounded = new RootBrowseSession();
        bounded.acceptStartResponse(0);
        equal(RootBrowseSession.AppendResult.LIMIT_REACHED,
                bounded.appendData(new byte[4096]),
                "first applicable record/byte limit latches");
        equal(true, bounded.rawData().length <= 4096,
                "latched browse data never exceeds byte limit");

        byte[] tenEntries = Hex.decode(
                "0800000000000000" + "0800000000000000"
                        + "0800000000000000" + "0800000000000000"
                        + "0800000000000000" + "0800000000000000"
                        + "0800000000000000" + "0800000000000000"
                        + "0800000000000000" + "0800000000000000");
        RootBrowseSession exactTen = new RootBrowseSession();
        exactTen.acceptStartResponse(0);
        equal(RootBrowseSession.AppendResult.LIMIT_REACHED,
                exactTen.appendData(tenEntries),
                "tenth complete record stops collection immediately");
        equal(false, exactTen.hasDataBeyondLimit(),
                "exactly ten records is not a protocol overrun");
        equal(RootBrowseSession.AppendResult.IGNORED_AFTER_LIMIT,
                exactTen.appendData(Hex.decode("0800000000000000")),
                "data after record limit is ignored while awaiting stop");
        equal(true, exactTen.hasDataBeyondLimit(),
                "post-limit data is recorded as protocol overrun");
        equal(10, exactTen.finish().entries.size(),
                "exactly ten retained records remain parseable");

        byte[] elevenEntries = concatenate(tenEntries, Hex.decode("0800000000000000"));
        RootBrowseSession elevenAtOnce = new RootBrowseSession();
        elevenAtOnce.acceptStartResponse(0);
        equal(RootBrowseSession.AppendResult.LIMIT_REACHED,
                elevenAtOnce.appendData(elevenEntries),
                "eleventh record in same chunk is not retained");
        equal(80, elevenAtOnce.rawData().length,
                "same-chunk overrun retains only first ten records");
        equal(true, elevenAtOnce.hasDataBeyondLimit(),
                "same-chunk eleventh record marks protocol overrun");
        equal(10, elevenAtOnce.finish().entries.size(),
                "same-chunk overrun still yields bounded evidence");
    }

    private static void testLegacyStorageHandleParsing() {
        byte[] responseData = Hex.decode(
                "FF160228"
                        + "00000000"
                        + "00000001"
                        + "00000002"
                        + "11223344"
                        + "55667788");
        equal(0x11223344L, RcspProtocol.selectInternalFlashHandle(responseData),
                "legacy storage selects FLASH before FLASH2");
    }

    private static void testLiveBadgeFilesystemHandleParsing() {
        byte[] responseData = Hex.decode(
                "FF1A0204000000000000000000000002000000000000000000000000");
        equal(0x00000002L, RcspProtocol.selectBadgeFilesystemHandle(responseData),
                "sole online SD Card 1 handle selected for badge filesystem probe");
        equal(-1L, RcspProtocol.selectBadgeFilesystemHandle(Hex.decode(
                        "FF1A0208000000000000000000000000000000020000000000000000")),
                "internal-flash index with numeric handle 2 is not SD Card 1");
        equal(-1L, RcspProtocol.selectBadgeFilesystemHandle(Hex.decode(
                        "FF1A020400000000000000000000000200000000000000000000000001")),
                "valid storage attribute followed by malformed trailing data fails closed");
        equal(0x00000002L, RcspProtocol.selectBadgeFilesystemHandle(Hex.decode(
                        "FF0B02FF000701010200000002")),
                "versioned online index-2 handle-2 record accepted");
        equal(-1L, RcspProtocol.selectBadgeFilesystemHandle(Hex.decode(
                        "FF0B02FF000701010300000002")),
                "versioned index-3 handle-2 record rejected");
        equal(-1L, RcspProtocol.selectBadgeFilesystemHandle(Hex.decode(
                        "FF1102FF000D01010200000002010200000002")),
                "duplicate index-2 records fail closed");
    }

    private static void testVersionedStorageHandleParsing() {
        byte[] responseData = Hex.decode(
                "FF0D02FF0009010000010311223344");
        equal(0x11223344L, RcspProtocol.selectInternalFlashHandle(responseData),
                "versioned storage selects online FLASH record");
        equal(-1L, RcspProtocol.selectInternalFlashHandle(
                        Hex.decode("FF0702FF0003010000")),
                "versioned storage rejects offline/non-flash records");
        equal(0x55667788L, RcspProtocol.selectInternalFlashHandle(
                        Hex.decode("FF1102FF000D01010611223344010555667788")),
                "versioned storage prefers FLASH2 over FLASH3");
        equal(-1L, RcspProtocol.selectInternalFlashHandle(
                        Hex.decode("FF0502FF000901")),
                "malformed versioned storage fails closed");
    }

    private static void testStorageProbeDecisions() {
        equal(ProbeSequence.Action.SEND_STORAGE_INFO,
                ProbeSequence.afterTargetInfoStatus(0),
                "target-info success queries storage only");
        equal(ProbeSequence.Action.SEND_ROOT_LISTING,
                ProbeSequence.afterStorageInfo(0, 0x00000002L),
                "live SD Card 1 handle starts one root listing");
        equal(ProbeSequence.Action.STOP,
                ProbeSequence.afterStorageInfo(0, 0x11223344L),
                "unexpected online handle fails closed");
        equal(ProbeSequence.Action.STOP,
                ProbeSequence.afterStorageInfo(0, -1L),
                "no internal flash handle stops");
        equal(ProbeSequence.Action.STOP,
                ProbeSequence.afterStorageInfo(2, 0x11223344L),
                "unknown storage command stops");
    }

    private static void testAdvertisementGate() {
        equal(true, ProbeSequence.matchesAdvertisement(
                        "47:84:00:01:8A:E9", "47:84:00:01:8a:e9"),
                "exact target advertisement accepted case-insensitively");
        equal(false, ProbeSequence.matchesAdvertisement(
                        "47:84:00:01:8A:E9", "47:84:00:01:8A:EA"),
                "other E87 address rejected");
        equal(false, ProbeSequence.matchesAdvertisement(
                        "47:84:00:01:8A:E9", null),
                "missing advertisement address rejected");
    }

    private static void testConnectionRetryGate() {
        equal(true, ProbeSequence.shouldRetryConnection(62, 1, true),
                "first pre-GATT status-62 failure gets one retry");
        equal(false, ProbeSequence.shouldRetryConnection(62, 2, true),
                "second status-62 failure stops");
        equal(false, ProbeSequence.shouldRetryConnection(133, 1, true),
                "unrelated GATT failure is not retried");
        equal(false, ProbeSequence.shouldRetryConnection(62, 1, false),
                "status-62 after authentication or RCSP start is not retried");
    }

    private static void testRunStateConsumesDuplicateResponses() {
        ProbeRunState state = new ProbeRunState();
        state.beginRequest(RcspProtocol.GET_TARGET_INFO, 1, 0);
        equal(ProbeRunState.ResponseResult.ACCEPTED,
                state.acceptResponse(RcspProtocol.GET_TARGET_INFO, 1, 10),
                "first target response consumed");
        equal(ProbeRunState.ResponseResult.IGNORED,
                state.acceptResponse(RcspProtocol.GET_TARGET_INFO, 1, 11),
                "duplicate target response ignored after consumption");

        state.beginRequest(RcspProtocol.GET_SYS_INFO, 2, 12);
        equal(ProbeRunState.ResponseResult.ACCEPTED,
                state.acceptResponse(RcspProtocol.GET_SYS_INFO, 2, 13),
                "first storage response consumed");
        equal(ProbeRunState.ResponseResult.IGNORED,
                state.acceptResponse(RcspProtocol.GET_SYS_INFO, 2, 14),
                "duplicate storage response ignored after consumption");

        state.beginRequest(RcspProtocol.START_FILE_BROWSE, 3, 1000);
        throwsIllegalState(
                () -> state.beginRequest(RcspProtocol.START_FILE_BROWSE, 4, 1001),
                "second root browse cannot begin while first is pending");
        equal(ProbeRunState.ResponseResult.ACCEPTED,
                state.acceptResponse(RcspProtocol.START_FILE_BROWSE, 3, 1002),
                "first browse-start response consumed");
        equal(ProbeRunState.ResponseResult.IGNORED,
                state.acceptResponse(RcspProtocol.START_FILE_BROWSE, 3, 1003),
                "duplicate browse-start response ignored after consumption");
        equal(true, state.hasStartedRcsp(), "state records RCSP transmission");
    }

    private static void testRunStateUsesAbsoluteBrowseDeadline() {
        ProbeRunState state = readyToBrowse(1000);
        equal(true, state.isReceivingBrowse(), "state enters browse receive phase");
        equal(19_999L, state.remainingBrowseMillis(1001),
                "deadline remaining time derives from fixed transmit timestamp");
        equal(ProbeRunState.BrowseEventResult.ACCEPTED,
                state.acceptBrowseData(20_999),
                "browse data just before deadline accepted");
        equal(ProbeRunState.BrowseEventResult.EXPIRED,
                state.acceptBrowseData(21_000),
                "browse data at absolute deadline rejected");
        equal(0L, state.remainingBrowseMillis(21_001),
                "expired deadline reports no remaining time");
        state.markTerminal();
        equal(ProbeRunState.BrowseEventResult.UNEXPECTED,
                state.acceptBrowseData(1002),
                "terminal state rejects browse data");

        ProbeRunState stopState = readyToBrowse(1000);
        equal(ProbeRunState.BrowseEventResult.ACCEPTED,
                stopState.beginAckDrain(0x7A, 1, 20_999),
                "stop just before deadline begins ACK drain");
        equal(true, stopState.isExactStopDuplicate(0x7A, 1),
                "identical stop recognized during ACK drain");
        equal(false, stopState.isExactStopDuplicate(0x7B, 1),
                "different stop sequence is not a duplicate");
        equal(false, stopState.isExactStopDuplicate(0x7A, 0),
                "different stop reason is not a duplicate");

        ProbeRunState expiredStop = readyToBrowse(1000);
        equal(ProbeRunState.BrowseEventResult.EXPIRED,
                expiredStop.beginAckDrain(0x7A, 1, 21_000),
                "stop at absolute deadline expires");
        equal(true, expiredStop.isExactStopDuplicate(0x7A, 1),
                "expired stop still enters ACK drain for exact re-acknowledgement");
    }

    private static ProbeRunState readyToBrowse(long startMillis) {
        ProbeRunState state = new ProbeRunState();
        state.beginRequest(RcspProtocol.GET_TARGET_INFO, 1, 0);
        state.acceptResponse(RcspProtocol.GET_TARGET_INFO, 1, 1);
        state.beginRequest(RcspProtocol.GET_SYS_INFO, 2, 2);
        state.acceptResponse(RcspProtocol.GET_SYS_INFO, 2, 3);
        state.beginRequest(RcspProtocol.START_FILE_BROWSE, 3, startMillis);
        state.acceptResponse(RcspProtocol.START_FILE_BROWSE, 3, startMillis + 1);
        return state;
    }

    private static void testFragmentedFrameAssemblyAndResync() {
        RcspFrameAssembler assembler = new RcspFrameAssembler(4096);
        equal(0, assembler.offer(Hex.decode("0099FEDCBA000300")).size(), "partial frame");
        List<byte[]> first = assembler.offer(Hex.decode("050044A1B2C3EF55FEDC"));
        equal(1, first.size(), "first assembled frame count");
        bytes(Hex.decode("FEDCBA000300050044A1B2C3EF"), first.get(0), "first frame");
        List<byte[]> second = assembler.offer(Hex.decode("BA00D600020001EF"));
        equal(1, second.size(), "second assembled frame count");
        bytes(Hex.decode("FEDCBA00D600020001EF"), second.get(0), "second frame");
    }

    private static void testAuthHandshake() {
        byte[] random = Hex.decode("000102030405060708090A0B0C0D0E0F10");
        byte[] deviceProof = Hex.decode("01112233445566778899AABBCCDDEEFF00");
        byte[] deviceChallenge = Hex.decode("00212233445566778899AABBCCDDEEFF00");
        byte[] challengeReply = Hex.decode("013132333435363738393A3B3C3D3E3F40");

        AuthProtocol.Crypto crypto = new AuthProtocol.Crypto() {
            @Override
            public byte[] random() {
                return random.clone();
            }

            @Override
            public byte[] encrypt(byte[] input) {
                if (Arrays.equals(input, random)) return deviceProof.clone();
                if (Arrays.equals(input, deviceChallenge)) return challengeReply.clone();
                throw new AssertionError("unexpected encrypt input " + Hex.encode(input));
            }
        };

        AuthProtocol auth = new AuthProtocol(crypto);
        AuthProtocol.Action begin = auth.begin();
        equal(AuthProtocol.ActionType.SEND, begin.type, "auth begin action");
        bytes(random, begin.bytes, "auth random");

        AuthProtocol.Action proof = auth.onReceive(deviceProof);
        equal(AuthProtocol.ActionType.SEND, proof.type, "device proof action");
        bytes(Hex.decode("0270617373"), proof.bytes, "phone auth-ok token");

        AuthProtocol.Action challenge = auth.onReceive(deviceChallenge);
        equal(AuthProtocol.ActionType.SEND, challenge.type, "challenge action");
        bytes(challengeReply, challenge.bytes, "challenge reply");

        AuthProtocol.Action success = auth.onReceive(Hex.decode("0270617373"));
        equal(AuthProtocol.ActionType.AUTHENTICATED, success.type, "auth success");
    }

    private static void testTargetInfoDecision() {
        equal(ProbeSequence.Action.SEND_STORAGE_INFO,
                ProbeSequence.afterTargetInfoStatus(0), "target-info success queries storage");
        equal(ProbeSequence.Action.STOP,
                ProbeSequence.afterTargetInfoStatus(2), "target-info failure stops");
    }

    private static void throwsIllegalArgument(Runnable action, String label) {
        try {
            action.run();
        } catch (IllegalArgumentException expected) {
            return;
        }
        throw new AssertionError(label + ": expected IllegalArgumentException");
    }

    private static void throwsIllegalState(Runnable action, String label) {
        try {
            action.run();
        } catch (IllegalStateException expected) {
            return;
        }
        throw new AssertionError(label + ": expected IllegalStateException");
    }

    private static void bytes(byte[] expected, byte[] actual, String label) {
        if (!Arrays.equals(expected, actual)) {
            throw new AssertionError(label + ": expected " + Hex.encode(expected)
                    + " but got " + Hex.encode(actual));
        }
    }

    private static byte[] concatenate(byte[] first, byte[] second) {
        byte[] result = Arrays.copyOf(first, first.length + second.length);
        System.arraycopy(second, 0, result, first.length, second.length);
        return result;
    }

    private static void equal(Object expected, Object actual, String label) {
        if (!expected.equals(actual)) {
            throw new AssertionError(label + ": expected " + expected + " but got " + actual);
        }
    }
}
