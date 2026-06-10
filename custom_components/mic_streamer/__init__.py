import esphome.codegen as cg
import esphome.config_validation as cv
from esphome import automation
from esphome.components import microphone
from esphome.const import CONF_ID, CONF_MICROPHONE, CONF_PORT

CODEOWNERS = ["@christian-natrop"]
DEPENDENCIES = ["microphone", "network"]
MULTI_CONF = True

CONF_ADDRESS = "address"
CONF_MAX_PACKET_SIZE = "max_packet_size"

mic_streamer_ns = cg.esphome_ns.namespace("mic_streamer")
MicStreamer = mic_streamer_ns.class_("MicStreamer", cg.Component)
StartAction = mic_streamer_ns.class_("StartAction", automation.Action)
StopAction = mic_streamer_ns.class_("StopAction", automation.Action)
IsStreamingCondition = mic_streamer_ns.class_("IsStreamingCondition", automation.Condition)

CONFIG_SCHEMA = cv.Schema(
    {
        cv.GenerateID(): cv.declare_id(MicStreamer),
        # 16- or 32-bit, 1 or 2 channels. Use channels: "0,1" for raw stereo
        # (both mics) or a single index to mirror what micro_wake_word consumes.
        cv.Optional(CONF_MICROPHONE, default={}): microphone.microphone_source_schema(
            min_bits_per_sample=16,
            max_bits_per_sample=32,
            min_channels=1,
            max_channels=2,
        ),
        # IPv4 address of the PC running tools/udp_audio_capture.py
        cv.Required(CONF_ADDRESS): cv.string,
        cv.Optional(CONF_PORT, default=6056): cv.port,
        # Stay under the network MTU to avoid IP fragmentation (4 bytes are
        # reserved for the per-datagram sequence header).
        cv.Optional(CONF_MAX_PACKET_SIZE, default=1024): cv.int_range(min=64, max=1460),
    }
).extend(cv.COMPONENT_SCHEMA)

FINAL_VALIDATE_SCHEMA = cv.Schema(
    {
        cv.Required(CONF_MICROPHONE): microphone.final_validate_microphone_source_schema(
            "mic_streamer"
        ),
    },
    extra=cv.ALLOW_EXTRA,
)


async def to_code(config):
    var = cg.new_Pvariable(config[CONF_ID])
    await cg.register_component(var, config)

    mic_source = await microphone.microphone_source_to_code(config[CONF_MICROPHONE])
    cg.add(var.set_microphone_source(mic_source))

    cg.add(var.set_address(str(config[CONF_ADDRESS])))
    cg.add(var.set_port(config[CONF_PORT]))
    cg.add(var.set_max_packet_size(config[CONF_MAX_PACKET_SIZE]))


MIC_STREAMER_ACTION_SCHEMA = automation.maybe_simple_id(
    {cv.GenerateID(): cv.use_id(MicStreamer)}
)


@automation.register_action("mic_streamer.start", StartAction, MIC_STREAMER_ACTION_SCHEMA)
async def mic_streamer_start_to_code(config, action_id, template_arg, args):
    var = cg.new_Pvariable(action_id, template_arg)
    await cg.register_parented(var, config[CONF_ID])
    return var


@automation.register_action("mic_streamer.stop", StopAction, MIC_STREAMER_ACTION_SCHEMA)
async def mic_streamer_stop_to_code(config, action_id, template_arg, args):
    var = cg.new_Pvariable(action_id, template_arg)
    await cg.register_parented(var, config[CONF_ID])
    return var


@automation.register_condition(
    "mic_streamer.is_streaming", IsStreamingCondition, MIC_STREAMER_ACTION_SCHEMA
)
async def mic_streamer_is_streaming_to_code(config, condition_id, template_arg, args):
    var = cg.new_Pvariable(condition_id, template_arg)
    await cg.register_parented(var, config[CONF_ID])
    return var
