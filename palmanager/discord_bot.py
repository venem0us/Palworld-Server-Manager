"""Only registered application commands; no message-content intent or message handlers."""
import asyncio,io,threading
import discord
from discord import app_commands
from .controller import render_map

def permitted(profile,command,user_id,role_ids):
    rule=profile.get('permissions',{}).get(command,{})
    return str(user_id) in rule.get('users',[]) or bool(set(map(str,role_ids))&set(rule.get('roles',[])))

class WorldBot:
    def __init__(self,profile,controller,token):
        self.profile=profile;self.controller=controller;self.token=token;self.loop=None;self.client=None;self.thread=None
    def start(self):
        if self.thread and self.thread.is_alive():raise RuntimeError('Bot is already running')
        self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()
    def stop(self):
        if self.loop and self.client:asyncio.run_coroutine_threadsafe(self.client.close(),self.loop)
    def run(self):
        asyncio.run(self.run_async())
    async def run_async(self):
        self.loop=asyncio.get_running_loop()
        outer=self
        class Client(discord.Client):
            async def setup_hook(self):
                await tree.sync(guild=discord.Object(id=int(outer.profile['guild_id'])))
            async def on_ready(self):outer.controller.listener(outer.profile['id'],'done','Discord bot connected as '+str(self.user))
        self.client=Client(intents=discord.Intents.none());tree=app_commands.CommandTree(self.client)
        guild=discord.Object(id=int(self.profile['guild_id']))
        async def dispatch(interaction,command,**kwargs):
            profile=next((p for p in outer.controller.store.profiles if p['id']==outer.profile['id']),outer.profile)
            roles=[r.id for r in getattr(interaction.user,'roles',[])]
            if interaction.guild_id!=int(profile['guild_id']) or not permitted(profile,command,interaction.user.id,roles):
                await interaction.response.send_message('You are not allowed to use this command.',ephemeral=True);return
            await interaction.response.defer(ephemeral=True,thinking=True)
            try:
                if command=='status':
                    state=await asyncio.to_thread(outer.controller.remote(profile).call,'status')
                    message=profile['name']+': '+state['ActiveState']+' · build '+state['build']
                elif command=='player-location':
                    data=await asyncio.to_thread(outer.controller.remote(profile).api,'players')
                    png=await asyncio.to_thread(render_map,profile,data.get('players',[]))
                    await interaction.followup.send(file=discord.File(io.BytesIO(png),filename='player-locations.png'),ephemeral=True);return
                else:
                    await asyncio.to_thread(outer.controller.operate,profile,command,**kwargs);message=command.capitalize()+' completed.'
                await interaction.followup.send(message,ephemeral=True,allowed_mentions=discord.AllowedMentions.none())
            except Exception as e:await interaction.followup.send(('Operation failed: '+str(e))[:1900],ephemeral=True,allowed_mentions=discord.AllowedMentions.none())
        @tree.command(name='start',description='Start this Palworld world',guild=guild)
        async def start(i:discord.Interaction):await dispatch(i,'start')
        @tree.command(name='stop',description='Warn players, save and stop this world',guild=guild)
        async def stop(i:discord.Interaction):await dispatch(i,'stop')
        @tree.command(name='restart',description='Warn players, save and restart this world',guild=guild)
        async def restart(i:discord.Interaction):await dispatch(i,'restart')
        @tree.command(name='backup',description='Take a consistent backup with a brief maintenance stop',guild=guild)
        async def backup(i:discord.Interaction):await dispatch(i,'backup')
        @tree.command(name='status',description='Read world status',guild=guild)
        async def status(i:discord.Interaction):await dispatch(i,'status')
        @tree.command(name='broadcast',description='Announce a message in game',guild=guild)
        async def broadcast(i:discord.Interaction,message:str):await dispatch(i,'broadcast',message=message)
        @tree.command(name='kick',description='Kick a player using the official REST API',guild=guild)
        async def kick(i:discord.Interaction,userid:str,message:str='Server administration'):await dispatch(i,'kick',userid=userid,message=message)
        @tree.command(name='player-location',description='Show a map of online player locations',guild=guild)
        async def location(i:discord.Interaction):await dispatch(i,'player-location')
        try:await self.client.start(self.token)
        except Exception as e:outer.controller.listener(outer.profile['id'],'error','Discord bot failed: '+type(e).__name__+' — check token, guild ID and bot invitation.')
